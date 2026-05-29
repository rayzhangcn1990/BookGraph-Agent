"""
Skill 基类定义

定义模块化内容生成 Skill 的标准接口：
- execute: LLM 分析
- validate: 结果校验
- generate_markdown: Markdown 生成
- run_and_write: 完整流程（执行→校验→写入）

🆕 改造：支持源文本对齐追踪
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

# 🆕 导入 Extraction 相关类型
from schemas.extraction_schema import (
    Extraction, ExtractionResult, AlignmentStatus,
    CharInterval, ChunkInfo
)

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class SkillResult:
    """Skill 执行结果"""
    skill_name: str
    success: bool
    result: Optional[Dict]
    errors: List[str]
    from_cache: bool = False
    elapsed_seconds: float = 0.0

    # 🆕 新增：Extraction 结果列表
    extractions: List[Extraction] = None

    def __post_init__(self):
        if self.extractions is None:
            self.extractions = []


class BaseSkill(ABC):
    """
    Skill 基类

    所有内容生成模块必须继承此基类，实现标准接口。
    """

    name: str = "base"              # Skill 名称
    section_name: str = ""          # Obsidian section 名称（用于增量写入）
    output_field: str = ""          # JSON 输出字段名
    min_items: int = 1              # 最少提取数量

    def __init__(self):
        """初始化 Skill"""
        self.retry_delays = [10, 30, 60]  # 指数退避（缩短初始延迟）
        self.max_retries = 3

    @property
    @abstractmethod
    def prompt_template(self) -> str:
        """专用提示词模板"""
        pass

    @abstractmethod
    def get_required_fields(self) -> List[str]:
        """获取必要字段列表"""
        pass

    # ═══════════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════════

    async def execute(
        self,
        llm_client,
        chunks: List[Dict],  # 🆕 改为 Dict 格式（包含 char_interval）
        book_title: str,
        use_cache: bool = True
    ) -> Dict:
        """
        执行 Skill：分析 chunks，提取结构化数据

        Args:
            llm_client: LLM 客户端
            chunks: chunk 列表 [(index, content, label)]
            book_title: 书名
            use_cache: 是否使用缓存

        Returns:
            Dict: 提取结果
        """
        import time
        start_time = time.time()

        # 检查缓存
        if use_cache:
            cached = self._get_cached_result(book_title)
            if cached:
                logger.info(f"[{self.name}] 使用缓存结果")
                return cached

        # 合并 chunks 内容（🆕 现在返回 Tuple[str, Dict]）
        combined_result = self._combine_chunks(chunks)
        combined_content, position_map = combined_result  # 解包 tuple

        # 🆕 保存位置映射，供后续对齐使用
        self._position_map = position_map

        # 构建提示词
        prompt = self.prompt_template.format(
            book_title=book_title,
            chunk_content=combined_content
        )

        # 调用 LLM（带重试和超时）
        for retry in range(self.max_retries):
            try:
                # 🔑 添加超时控制（最多3分钟）
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        llm_client._call_llm,
                        [
                            {"role": "system", "content": self._get_system_prompt()},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=16384,
                    ),
                    timeout=180  # 3分钟超时
                )

                if response is None:
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"[{self.name}] 空响应，{delay}s后重试")
                    await asyncio.sleep(delay)
                    continue

                # 解析 JSON
                result = self._parse_response(response)

                if result:
                    # 保存缓存
                    self._save_cached_result(book_title, result)
                    elapsed = time.time() - start_time
                    logger.info(f"✅ [{self.name}] 完成 ({elapsed:.1f}s)")
                    return result
                else:
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"[{self.name}] 解析失败，{delay}s后重试")
                    await asyncio.sleep(delay)

            except asyncio.TimeoutError:
                logger.error(f"[{self.name}] LLM调用超时（180s）")
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delays[0])
                continue

            except Exception as e:
                error_str = str(e)
                if '429' in error_str or 'rate limit' in error_str.lower():
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)] * 2
                    logger.warning(f"[{self.name}] 限流，{delay}s后重试")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"[{self.name}] 异常: {error_str[:100]}")
                    if retry < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delays[0])

        # 所有重试失败
        logger.error(f"❌ [{self.name}] 重试耗尽")
        return self._create_fallback_result(["LLM 调用失败"])

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """
        校验结果

        Args:
            result: 提取结果

        Returns:
            Tuple[bool, List[str]]: (是否合格, 错误列表)
        """
        errors = []

        # Layer 1: 结构校验
        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        # Layer 2: 字段校验
        required_fields = self.get_required_fields()
        for field in required_fields:
            if field not in result:
                errors.append(f"缺失字段: {field}")
            elif not result[field]:
                errors.append(f"字段为空: {field}")

        # Layer 3: 数量校验
        items = result.get(self.output_field, [])
        if len(items) < self.min_items:
            errors.append(f"提取数量不足: {len(items)} < {self.min_items}")

        # Layer 4: 内容质量校验
        quality_errors = self._validate_content_quality(items)
        errors.extend(quality_errors)

        return len(errors) == 0, errors

    @abstractmethod
    def generate_markdown(
        self,
        result: Dict,
        extractions: List[Extraction] = None  # 🆕 新增参数
    ) -> str:
        """
        生成 Markdown 内容

        🆕 改造：接收 extractions 参数，用于显示位置引用

        Args:
            result: 提取结果
            extractions: Extraction 列表（带位置信息）

        Returns:
            str: Markdown 内容（可包含位置引用链接）
        """
        pass

    async def run_and_write(
        self,
        llm_client,
        chunks: List[Dict],  # 🆕 改为 Dict 格式
        book_title: str,
        obsidian_writer,
        discipline: str
    ) -> SkillResult:
        """
        完整流程：执行 → 校验 → 写入

        Args:
            llm_client: LLM 客户端
            chunks: chunk 列表
            book_title: 书名
            obsidian_writer: Obsidian 写入器
            discipline: 学科

        Returns:
            SkillResult: 执行结果
        """
        import time
        start_time = time.time()

        # Step 1: 执行
        result = await self.execute(llm_client, chunks, book_title)

        # Step 2: 校验
        is_valid, errors = self.validate(result)

        if not is_valid:
            logger.warning(f"⚠️ [{self.name}] 校验失败: {errors}")
            # 校验失败时，使用后备结果
            result = self._create_fallback_result(errors)

        # 🆕 Step 2.5: 创建 Extractions（源文本对齐）
        extractions = []
        if is_valid and hasattr(self, '_position_map') and self._position_map:
            extractions = self._convert_result_to_extractions(result)

        # Step 3: 生成 Markdown（🆕 传入 extractions）
        markdown = self.generate_markdown(result, extractions=extractions)

        # Step 4: 增量写入
        try:
            obsidian_writer.update_section(
                discipline=discipline,
                book_title=book_title,
                section_name=self.section_name,
                section_content=markdown
            )
            logger.info(f"📝 [{self.name}] 增量写入完成")
        except Exception as e:
            logger.error(f"❌ [{self.name}] 写入失败: {e}")
            errors.append(f"写入失败: {str(e)[:50]}")
            is_valid = False

        elapsed = time.time() - start_time

        return SkillResult(
            skill_name=self.name,
            success=is_valid,
            result=result,
            errors=errors,
            extractions=extractions,  # 🆕 填充 extractions
            elapsed_seconds=elapsed
        )

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的学术书籍分析专家。请严格按照 JSON 格式输出，不要添加任何 Markdown 代码块标记或额外说明。

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"TBD"、"TODO"、"N/A"等占位符
2. 所有内容必须有实质性信息
3. 底层逻辑必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
4. 输出纯 JSON，不含任何其他内容"""

    def _combine_chunks(
        self,
        chunks: List[Dict],
        max_chunks: int = 5,
        max_chars_per_chunk: int = 8000
    ) -> Tuple[str, Dict]:
        """
        合并 chunks 内容（智能采样版）

        🆕 改造：
        1. 适配新的 Dict 格式 chunks（包含 char_interval）
        2. 返回位置映射（用于后续对齐）

        Args:
            chunks: chunk 列表，每个元素是 Dict:
                - chunk_index: 序号
                - content: 内容
                - label: 标签
                - char_interval: {start_pos, end_pos}
                - source_text: 完整原文
            max_chunks: 每段最大采样数量
            max_chars_per_chunk: 每块最大字符数

        Returns:
            Tuple[str, Dict]: (合并内容, 位置映射)
                位置映射格式: {
                    "source_text": 完整原文,
                    "chunk_positions": [
                        {"chunk_index": 0, "start_pos": 100, "end_pos": 200, "label": "第一章"},
                        ...
                    ]
                }
        """
        total_chunks = len(chunks)

        # 🔑 智能采样策略
        if total_chunks <= max_chunks * 2:
            selected_indices = range(total_chunks)
        else:
            head_count = max_chunks
            tail_count = max_chunks
            middle_count = max_chunks

            head_indices = list(range(0, head_count))
            middle_start = total_chunks // 2 - middle_count // 2
            middle_indices = list(range(middle_start, middle_start + middle_count))
            tail_indices = list(range(total_chunks - tail_count, total_chunks))

            selected_indices = sorted(set(head_indices + middle_indices + tail_indices))

        combined = []
        chunk_positions = []
        source_text = ""

        for idx in selected_indices:
            if idx < len(chunks):
                chunk = chunks[idx]
                content = chunk.get("content", "")
                label = chunk.get("label", f"Chunk {idx}")
                char_interval = chunk.get("char_interval", {"start_pos": 0, "end_pos": 0})

                # 🆕 记录位置信息
                chunk_positions.append({
                    "chunk_index": idx,
                    "start_pos": char_interval.get("start_pos", 0),
                    "end_pos": char_interval.get("end_pos", 0),
                    "label": label,
                    "combined_start": len("\n\n---\n\n".join(combined)) if combined else 0
                })

                # 保存完整原文
                if not source_text and chunk.get("source_text"):
                    source_text = chunk.get("source_text", "")

                truncated_content = content[:max_chars_per_chunk]
                combined.append(f"【{label}】\n{truncated_content}")

        result_content = "\n\n---\n\n".join(combined)
        total_chars = len(result_content)
        coverage = len(selected_indices) / total_chunks * 100

        position_map = {
            "source_text": source_text,
            "chunk_positions": chunk_positions,
            "combined_length": total_chars
        }

        logger.info(f"[{self.name}] 智能采样: {len(selected_indices)}/{total_chunks} chunks ({coverage:.1f}%覆盖), {total_chars} 字符")

        return result_content, position_map

        return result

    def _parse_response(self, response: str) -> Optional[Dict]:
        """解析 LLM 响应"""
        try:
            # 清理 Markdown 代码块
            response = re.sub(r'^```json\s*', '', response)
            response = re.sub(r'^```\s*', '', response)
            response = re.sub(r'\s*```$', '', response)

            # 找 JSON
            json_start = response.find('{')
            if json_start < 0:
                return None

            # 深度匹配
            depth = 0
            json_end = json_start
            for i, c in enumerate(response[json_start:], json_start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_end = i + 1
                        break

            json_str = response[json_start:json_end]
            result = json.loads(json_str)

            # 规范化字段名
            result = self._normalize_field_names(result)

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"[{self.name}] JSON 解析失败: {e}")
            return None

    def _normalize_field_names(self, result: Dict) -> Dict:
        """规范化字段名"""
        # 使用 model_output_format_spec 的映射
        from core.model_output_format_spec import normalize_field_names
        return normalize_field_names(result)

    def _validate_content_quality(self, items: List) -> List[str]:
        """校验内容质量"""
        errors = []

        placeholders = [
            "待分析", "待补充", "待填写", "待生成",
            "TBD", "TODO", "N/A", "NULL", "None",
            "暂无", "无", "未涉及",
            "（此处内容由 LLM 生成）",
            "（内容由模型生成）",
        ]

        for i, item in enumerate(items):
            if isinstance(item, dict):
                for key, value in item.items():
                    if isinstance(value, str):
                        for ph in placeholders:
                            if ph in value:
                                errors.append(f"项目{i+1} 包含占位符: {key}")
                                break

        return errors

    def _get_cached_result(self, book_title: str) -> Optional[Dict]:
        """获取缓存结果"""
        from utils.parse_cache import get_cache
        cache = get_cache()
        # 使用专用缓存键
        cache_key = f"{book_title}_{self.name}"
        return cache.get(cache_key)

    def _save_cached_result(self, book_title: str, result: Dict):
        """保存缓存结果"""
        from utils.parse_cache import get_cache
        cache = get_cache()
        cache_key = f"{book_title}_{self.name}"
        cache.set(cache_key, result)

    def _create_fallback_result(self, errors: List[str]) -> Dict:
        """创建后备结果"""
        return {
            "extraction_status": "failed",
            "errors": errors,
            "fallback_note": f"此部分内容生成失败，待手动修复",
            self.output_field: []
        }

    # ═══════════════════════════════════════════════════════════
    # 🆕 源文本对齐方法（借鉴 langextract）
    # ═══════════════════════════════════════════════════════════

    def _create_extraction(
        self,
        extraction_class: str,
        extraction_text: str,
        position_map: Dict,
        attributes: Dict = None
    ) -> Extraction:
        """
        创建单条 Extraction（自动对齐到原文）

        Args:
            extraction_class: 提取类型（concept/insight/case等）
            extraction_text: 提取的文本
            position_map: 位置映射（包含 source_text）
            attributes: 额外属性

        Returns:
            Extraction: 带位置信息的提取结果
        """
        source_text = position_map.get("source_text", "")

        # 🔑 尝试对齐到原文
        char_interval, alignment_status = self._align_extraction(
            extraction_text, source_text
        )

        return Extraction(
            extraction_class=extraction_class,
            extraction_text=extraction_text,
            char_interval=char_interval,
            alignment_status=alignment_status,
            attributes=attributes,
            source_snippet=source_text[char_interval.start_pos:char_interval.end_pos] if char_interval else None
        )

    def _align_extraction(
        self,
        extraction_text: str,
        source_text: str,
        fuzzy_threshold: float = 0.75
    ) -> Tuple[Optional[CharInterval], AlignmentStatus]:
        """
        将提取文本对齐到原文位置

        使用 LCS（最长公共子序列）算法实现模糊匹配。
        借鉴 langextract 的 Resolver 设计。

        Args:
            extraction_text: LLM 提取的文本
            source_text: 完整原文
            fuzzy_threshold: 模糊匹配阈值（默认 75%）

        Returns:
            Tuple[Optional[CharInterval], AlignmentStatus]: (位置区间, 对齐状态)
        """
        if not extraction_text or not source_text:
            return None, AlignmentStatus.UNGROUNDED

        # 1. 尝试精确匹配
        exact_pos = source_text.find(extraction_text)
        if exact_pos >= 0:
            return CharInterval(
                start_pos=exact_pos,
                end_pos=exact_pos + len(extraction_text)
            ), AlignmentStatus.MATCH_EXACT

        # 2. 尝试 LCS 模糊匹配
        best_match = self._lcs_find_position(extraction_text, source_text)

        if best_match:
            match_text = source_text[best_match["start"]:best_match["end"]]
            similarity = best_match["similarity"]

            if similarity >= fuzzy_threshold:
                # 根据匹配长度判断状态
                if len(match_text) > len(extraction_text):
                    status = AlignmentStatus.MATCH_GREATER
                elif len(match_text) < len(extraction_text):
                    status = AlignmentStatus.MATCH_LESSER
                else:
                    status = AlignmentStatus.MATCH_FUZZY

                return CharInterval(
                    start_pos=best_match["start"],
                    end_pos=best_match["end"]
                ), status

        # 3. 无法定位
        return None, AlignmentStatus.UNGROUNDED

    def _lcs_find_position(
        self,
        pattern: str,
        text: str
    ) -> Optional[Dict]:
        """
        LCS 算法：在 text 中找到 pattern 的最佳匹配位置

        实现最长公共子序列匹配，返回最佳匹配区间。

        Args:
            pattern: 待匹配文本（LLM提取）
            text: 源文本

        Returns:
            Optional[Dict]: {
                "start": 起始位置,
                "end": 结束位置,
                "similarity": 相似度,
                "matched_length": 匹配长度
            }
        """
        if not pattern or not text:
            return None

        pattern_len = len(pattern)
        text_len = len(text)

        # 滑动窗口搜索
        best_match = None
        best_similarity = 0

        # 优化：只在可能匹配的区域搜索
        # 搜索窗口大小 = pattern长度 * 1.5（允许一定扩展）
        window_size = int(pattern_len * 1.5)
        step = max(1, pattern_len // 4)  # 步长

        for start in range(0, text_len - pattern_len + 1, step):
            end = min(start + window_size, text_len)
            window_text = text[start:end]

            # 计算 LCS 长度
            lcs_length = self._compute_lcs_length(pattern, window_text)

            # 计算相似度
            similarity = lcs_length / pattern_len

            if similarity > best_similarity:
                best_similarity = similarity
                # 精确定位匹配区间（尝试缩小范围）
                refined_start, refined_end = self._refine_match_position(
                    pattern, text, start, end
                )
                best_match = {
                    "start": refined_start,
                    "end": refined_end,
                    "similarity": similarity,
                    "matched_length": lcs_length
                }

        return best_match if best_similarity > 0.5 else None

    def _compute_lcs_length(self, s1: str, s2: str) -> int:
        """
        计算两个字符串的最长公共子序列长度

        使用动态规划实现。

        Args:
            s1: 字符串1
            s2: 字符串2

        Returns:
            int: LCS 长度
        """
        m, n = len(s1), len(s2)

        # 优化：对于长字符串，使用滚动数组
        if m > 500 or n > 500:
            # 简化版：只计算近似 LCS
            return self._approximate_lcs(s1, s2)

        # DP 表
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i-1] == s2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])

        return dp[m][n]

    def _approximate_lcs(self, s1: str, s2: str) -> int:
        """
        近似 LCS 计算（用于长字符串）

        使用贪心策略，牺牲精度换取速度。

        Args:
            s1: 字符串1
            s2: 字符串2

        Returns:
            int: 近似 LCS 长度
        """
        matched = 0
        s2_idx = 0

        for ch in s1:
            # 在 s2 中找当前字符
            pos = s2.find(ch, s2_idx)
            if pos >= 0:
                matched += 1
                s2_idx = pos + 1

        return matched

    def _refine_match_position(
        self,
        pattern: str,
        text: str,
        rough_start: int,
        rough_end: int
    ) -> Tuple[int, int]:
        """
        精细化匹配位置

        在粗略匹配区间内，找到精确的起始和结束位置。

        Args:
            pattern: 待匹配文本
            text: 源文本
            rough_start: 粗略起始位置
            rough_end: 粗略结束位置

        Returns:
            Tuple[int, int]: (精确起始, 精确结束)
        """
        window = text[rough_start:rough_end]

        # 尝试找到 pattern 首字符在 window 中的位置
        first_char = pattern[0] if pattern else ""
        if first_char:
            first_pos = window.find(first_char)
            if first_pos >= 0:
                refined_start = rough_start + first_pos
                # 尝试匹配末尾
                last_char = pattern[-1] if pattern else ""
                last_pos = window.rfind(last_char)
                if last_pos >= first_pos:
                    refined_end = rough_start + last_pos + 1
                    return refined_start, refined_end

        return rough_start, rough_end

    def _create_extraction_result(
        self,
        extractions: List[Extraction],
        success: bool = True,
        errors: List[str] = None
    ) -> ExtractionResult:
        """
        创建 ExtractionResult 汇总

        Args:
            extractions: Extraction 列表
            success: 是否成功
            errors: 错误列表

        Returns:
            ExtractionResult: 汇总结果
        """
        result = ExtractionResult(
            skill_name=self.name,
            extractions=extractions,
            success=success,
            errors=errors or []
        )
        result.compute_stats()
        return result

    def _convert_result_to_extractions(self, result: Dict) -> List[Extraction]:
        """
        将 JSON Dict 结果转换为 Extraction 列表

        🆕 真正集成 Extraction 到数据流

        Args:
            result: execute() 返回的 Dict 结果

        Returns:
            List[Extraction]: 带位置信息的提取列表
        """
        extractions = []
        position_map = getattr(self, '_position_map', {})
        source_text = position_map.get('source_text', '')

        if not source_text:
            return extractions

        # 从 result 中提取各个项目
        items = result.get(self.output_field, [])

        for idx, item in enumerate(items):
            if isinstance(item, dict):
                # 尝试提取主要文本字段
                extraction_text = self._extract_main_text(item)
                if extraction_text:
                    extraction = self._create_extraction(
                        extraction_class=self.name,
                        extraction_text=extraction_text,
                        position_map=position_map,
                        attributes=item  # 保存完整属性
                    )
                    extractions.append(extraction)

        # 打印对齐统计
        grounded = sum(1 for e in extractions if e.is_grounded())
        logger.info(f"[{self.name}] 源文本对齐: {grounded}/{len(extractions)} 条成功定位")

        return extractions

    def _extract_main_text(self, item: Dict) -> Optional[str]:
        """
        从 Dict 中提取主要文本字段（用于对齐）

        不同 Skill 有不同的主字段，子类可覆盖此方法。

        Args:
            item: 单条提取 Dict

        Returns:
            Optional[str]: 主要文本
        """
        # 默认字段优先级
        priority_fields = ['name', 'title', 'concept_name', 'quote_text', 'text', 'description']

        for field in priority_fields:
            if field in item and isinstance(item[field], str):
                return item[field]

        return None