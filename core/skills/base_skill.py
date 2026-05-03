"""
Skill 基类定义

定义模块化内容生成 Skill 的标准接口：
- execute: LLM 分析
- validate: 结果校验
- generate_markdown: Markdown 生成
- run_and_write: 完整流程（执行→校验→写入）
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

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
        chunks: List[Tuple[int, str, str]],
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

        # 合并 chunks 内容
        combined_content = self._combine_chunks(chunks)

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
                        max_tokens=16384
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
    def generate_markdown(self, result: Dict) -> str:
        """
        生成 Markdown 内容

        Args:
            result: 提取结果

        Returns:
            str: Markdown 内容
        """
        pass

    async def run_and_write(
        self,
        llm_client,
        chunks: List[Tuple[int, str, str]],
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

        # Step 3: 生成 Markdown
        markdown = self.generate_markdown(result)

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

    def _combine_chunks(self, chunks: List[Tuple[int, str, str]], max_chunks: int = 5, max_chars_per_chunk: int = 8000) -> str:
        """
        合并 chunks 内容（智能截断版）

        Args:
            chunks: chunk 列表 [(index, content, label)]
            max_chunks: 最大合并数量（避免输入超长）
            max_chars_per_chunk: 每块最大字符数

        Returns:
            str: 合并后的内容（控制在 token 限制内）
        """
        combined = []

        # 🔑 只取前 max_chunks 个 chunks（避免输入超长）
        selected_chunks = chunks[:max_chunks]

        for idx, content, label in selected_chunks:
            # 🔑 每块截断到 max_chars_per_chunk
            truncated_content = content[:max_chars_per_chunk]
            combined.append(f"【{label}】\n{truncated_content}")

        result = "\n\n---\n\n".join(combined)

        # 🔑 日志提示
        total_chars = len(result)
        logger.info(f"[{self.name}] 输入截断: {len(selected_chunks)}/{len(chunks)} chunks, {total_chars} 字符")

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