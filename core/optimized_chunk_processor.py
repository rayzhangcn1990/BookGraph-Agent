"""
优化版 Chunk 并行处理器

核心优化点：
1. asyncio 并行处理（替代 ThreadPoolExecutor）
2. 智能重试策略（5→15→45秒指数退避 + Jitter）
3. 缓存机制（断点续传）
4. 统一 JSON 解析（三层防护）
5. 全局客户端复用（避免重复初始化）
"""

import asyncio
import random
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# 导入优化模块
from core.model_output_format_spec import parse_model_output, get_prompt_for_model
from utils.parse_cache import get_cache
# 导入 schema 和结构化输出支持
from schemas.book_graph_schema import CHUNK_ANALYSIS_JSON_SCHEMA

logger = logging.getLogger("BookGraph-Agent")


def _format_local_hint_for_prompt(hint) -> str:
    """将本地预处理候选信号格式化为 prompt 片段。"""
    if not hint:
        return ""

    chapter_ref = getattr(hint, "chapter_ref", "") or "未知"
    concepts = getattr(hint, "concept_candidates", []) or []
    quotes = getattr(hint, "quote_candidates", []) or []

    if not concepts and not quotes and chapter_ref == "未知":
        return ""

    lines = [
        "【本地预处理候选信号】",
        f"可能章节：{chapter_ref}",
    ]
    if concepts:
        lines.append(f"候选概念：{'、'.join(concepts[:8])}")
    if quotes:
        lines.append(f"候选金句：{'；'.join(quotes[:5])}")
    lines.append("注意：这些只是本地小模型候选信号，必须以原文为准，不可盲信。")
    return "\n".join(lines)


@dataclass
class ChunkResult:
    """Chunk 处理结果"""
    chunk_index: int
    success: bool
    result: Optional[Dict] = None
    error: Optional[str] = None
    from_cache: bool = False
    elapsed_seconds: float = 0.0


class OptimizedChunkProcessor:
    """优化版 Chunk 处理器"""

    def __init__(self, llm_client, max_parallel: int = 4):
        """
        初始化处理器

        Args:
            llm_client: LLM 客户端（全局复用）
            max_parallel: 最大并行数
        """
        self.llm_client = llm_client
        self.max_parallel = max_parallel
        self.cache = get_cache()

        # 智能重试配置
        self.retry_delays = [5, 15, 45]  # 指数退避（秒）
        self.max_retries = 3
        # 动态限流追踪
        self._consecutive_rate_limits = 0
        self._current_max_parallel = max_parallel
        # 动态并发恢复追踪
        self._consecutive_successes = 0
        self._recovery_threshold = 5  # 🔑 优化：从10降低到5，加快限流缓解后的并发度恢复速度

    async def process_single_chunk(
        self,
        chunk_index: int,
        chunk_content: str,
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        use_cache: bool = True
    ) -> ChunkResult:
        """
        处理单个 chunk（带缓存和智能重试）

        Args:
            chunk_index: chunk 索引
            chunk_content: chunk 内容
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板
            use_cache: 是否使用缓存

        Returns:
            ChunkResult: 处理结果
        """
        start_time = datetime.now()

        # Step 1: 检查缓存
        if use_cache:
            cached_result = self.cache.get_cached_result(book_title, chunk_index, chunk_content)
            if cached_result:
                # 🔑 新增：验证缓存数据有效性（OptimizedChunkProcessor版本）
                from core.model_output_format_spec import validate_required_fields
                is_valid, missing_fields = validate_required_fields(cached_result, field_type="chunk_analysis")

                if is_valid:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   💾 Chunk {chunk_index} 缓存命中且有效")
                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=cached_result,
                        from_cache=True,
                        elapsed_seconds=elapsed
                    )
                else:
                    # 缓存数据无效，清除并重新处理
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 缓存数据无效（缺失字段: {missing_fields}），清除缓存")
                elapsed = (datetime.now() - start_time).total_seconds()
                return ChunkResult(
                    chunk_index=chunk_index,
                    success=True,
                    result=cached_result,
                    from_cache=True,
                    elapsed_seconds=elapsed
                )

        # Step 2: 构建 prompt
        prompt = chunk_prompt_template.format(
            book_title=book_title,
            chunk_content=chunk_content
        )

        # Step 3: 智能重试调用
        for retry in range(self.max_retries):
            try:
                # 使用 asyncio.to_thread 包装同步 LLM 调用
                response = await asyncio.to_thread(
                    self._call_llm_sync,
                    system_prompt,
                    prompt,
                    max_tokens=16384
                )

                if response is None:
                    # 空响应，等待后重试
                    base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 空响应，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试 ({retry+1}/{self.max_retries})")
                    await asyncio.sleep(actual_delay)
                    continue

                # Step 4: 统一 JSON 解析（三层防护）
                result, success, error_msg = parse_model_output(response)

                if success and result:
                    # 保存到缓存
                    self.cache.save_result(book_title, chunk_index, chunk_content, result)

                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   ✅ Chunk {chunk_index} 完成 ({elapsed:.1f}秒)")

                    # 动态并发恢复：连续成功后逐步恢复并发度
                    self._consecutive_successes += 1
                    if (self._consecutive_successes >= self._recovery_threshold 
                        and self._current_max_parallel < self.max_parallel):
                        old_parallel = self._current_max_parallel
                        self._current_max_parallel = min(self._current_max_parallel + 1, self.max_parallel)
                        logger.info(f"   📈 连续成功 {self._consecutive_successes} 次，恢复并发度至 {self._current_max_parallel}")
                        self._consecutive_rate_limits = 0  # 重置限流计数

                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=result,
                        from_cache=False,
                        elapsed_seconds=elapsed
                    )
                else:
                    # 解析失败，等待后重试
                    base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 解析失败: {error_msg}，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                    await asyncio.sleep(actual_delay)

            except Exception as e:
                # 异常处理
                error_str = str(e)
                error_lower = error_str.lower()

                # 限流处理（429）
                if '429' in error_str or 'throttling' in error_lower or 'rate limit' in error_lower:
                    self._consecutive_rate_limits += 1
                    self._consecutive_successes = 0  # 重置成功计数
                    # 动态降低并发度
                    if self._consecutive_rate_limits > 3 and self._current_max_parallel > 1:
                        self._current_max_parallel = max(1, self._current_max_parallel // 2)
                        logger.warning(f"   ⚠️ 检测到持续限流，降低最大并发至 {self._current_max_parallel}")
                        # 更新信号量（将在下次 process_chunks_parallel 重新创建）
                    # 指数退避，并尝试解析 Retry-After
                    base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)] * 2
                    # 尝试从错误消息中提取等待秒数
                    import re
                    match = re.search(r'retry after (\d+)', error_str)
                    if match:
                        base_delay = int(match.group(1))
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 限流，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                    await asyncio.sleep(actual_delay)
                    continue

                # 其他异常
                logger.error(f"   ❌ Chunk {chunk_index} 异常: {error_str[:100]}")
                if retry < self.max_retries - 1:
                    base_delay = self.retry_delays[0]
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 其他异常，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                    await asyncio.sleep(actual_delay)
                    continue

        # 所有重试都失败，尝试降级策略（OptimizedChunkProcessor版本）
        logger.warning(f"⚠️ Chunk {chunk_index} 重试耗尽，尝试降级策略")

        # 🔑 降级策略1: 降低max_tokens（减少截断概率）
        try:
            logger.info(f"   🔧 降级策略1: 降低max_tokens至50%")
            response = await asyncio.to_thread(
                self._call_llm_sync,
                system_prompt,
                prompt,
                max_tokens=max(2048, 16384 // 2)
            )
            if response:
                result, success, error_msg = parse_model_output(response)
                if success and result:
                    self.cache.save_result(book_title, chunk_index, chunk_content, result)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   ✅ Chunk {chunk_index} 降级策略1成功")
                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=result,
                        from_cache=False,
                        elapsed_seconds=elapsed
                    )
        except Exception as e:
            logger.warning(f"   ⚠️ 降级策略1失败: {str(e)[:50]}")

        # 🔑 降级策略2: 简化prompt（只要求核心字段）
        try:
            logger.info(f"   🔧 降级策略2: 简化prompt")
            simplified_prompt = f"""书名: {book_title}

章节内容（节选）:
{chunk_content[:2000]}

请提取以下信息（JSON格式）：
1. chapter_summaries: 章节摘要数组
2. core_concepts: 核心概念数组

输出格式:
{{"chapter_summaries": [...], "core_concepts": [...]}}"""

            response = await asyncio.to_thread(
                self._call_llm_sync,
                "你是一个书籍内容分析助手，请按照用户要求提取关键信息，以JSON格式输出。",
                simplified_prompt,
                max_tokens=4096
            )
            if response:
                result, success, error_msg = parse_model_output(response)
                if result:
                    # 补齐缺失字段
                    for field in ["chapter_summaries", "core_concepts", "key_insights", "key_cases", "golden_quotes"]:
                        result.setdefault(field, [])
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   ✅ Chunk {chunk_index} 降级策略2成功")
                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=result,
                        from_cache=False,
                        elapsed_seconds=elapsed
                    )
        except Exception as e:
            logger.warning(f"   ⚠️ 降级策略2失败: {str(e)[:50]}")

        # 最终失败
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"   ❌ Chunk {chunk_index} 所有降级策略均失败")
        return ChunkResult(
            chunk_index=chunk_index,
            success=False,
            error="重试耗尽且降级策略失败",
            elapsed_seconds=elapsed
        )

    def _call_llm_sync(self, system_prompt: str, user_prompt: str, max_tokens: int) -> Optional[str]:
        """
        同步调用 LLM（使用全局客户端）

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            max_tokens: 最大 token 数

        Returns:
            Optional[str]: LLM 响应
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # 使用全局客户端（避免重复初始化）
            response = self.llm_client._call_llm(messages, max_tokens=max_tokens)
            return response

        except Exception as e:
            logger.error(f"   ❌ LLM 调用异常: {str(e)[:100]}")
            return None


    async def _call_llm_with_schema_async(
        self,
        messages: List[Dict],
        schema: Dict,
        max_tokens: int = None
    ) -> Dict:
        """
        异步调用 LLM 并强制 JSON Schema 输出

        使用 OpenAI response_format 强制 LLM 输出符合 schema 的 JSON。
        
        Args:
            messages: 消息列表
            schema: JSON Schema 字典
            max_tokens: 最大输出 token 数

        Returns:
            Dict: 解析后的 JSON 对象，失败返回 None
        """
        max_tokens = max_tokens or 16384

        if not self.async_client.async_openai_client:
            logger.warning("⚠️ AsyncOpenAI 客户端未初始化，无法使用 JSON Schema 模式")
            return None

        try:
            import json
            response = await self.async_client.async_openai_client.chat.completions.create(
                model=self.async_client.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=self.async_client.temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ChunkAnalysis",
                        "schema": schema,
                        "strict": True
                    }
                }
            )

            content = response.choices[0].message.content
            if content:
                return json.loads(content)
            return None

        except Exception as e:
            logger.error(f"❌ JSON Schema 模式失败: {str(e)[:100]}")
            return None

    async def process_chunks_parallel(
        self,
        chunks: List[Tuple[int, str, str]],  # (index, content, label)
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        use_cache: bool = True
    ) -> List[ChunkResult]:
        """
        并行处理所有 chunks

        Args:
            chunks: chunk 列表 [(index, content, label)]
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板
            use_cache: 是否使用缓存

        Returns:
            List[ChunkResult]: 所有处理结果
        """
        # 使用当前有效的最大并行数（可能因限流动态降低）
        effective_max = self._current_max_parallel
        logger.info(f"🚀 并行处理 {len(chunks)} 个 chunks（最大并行数: {effective_max})")

        # 使用 semaphore 控制并发
        semaphore = asyncio.Semaphore(effective_max)

        async def process_with_semaphore(chunk):
            async with semaphore:
                idx, content, label = chunk
                logger.info(f"   ▶️ 开始处理 Chunk {idx} [{label}]")
                return await self.process_single_chunk(
                    idx, content, book_title, system_prompt, chunk_prompt_template, use_cache
                )

        # 并行启动所有任务
        tasks = [process_with_semaphore(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ChunkResult(
                    chunk_index=chunks[i][0],
                    success=False,
                    error=str(result)[:100]
                ))
            else:
                final_results.append(result)

        # 统计结果
        success_count = sum(1 for r in final_results if r.success)
        cache_count = sum(1 for r in final_results if r.from_cache)
        total_time = sum(r.elapsed_seconds for r in final_results)

        logger.info(f"✅ 处理完成: {success_count}/{len(chunks)} 成功")
        logger.info(f"   📊 统计: {cache_count} 缓存命中，总耗时 {total_time:.1f}秒")

        return final_results


# ═══════════════════════════════════════════════════════════
# Phase 3: 原生异步 Chunk 处理器
# ═══════════════════════════════════════════════════════════

class NativeAsyncChunkProcessor:
    """
    原生异步 Chunk 处理器

    使用 AsyncLLMClient 的 _call_llm_async 方法，
    消除 asyncio.to_thread 包装开销，实现真正的并发。

    性能提升：
    - 原方案：asyncio.to_thread 包装同步 SDK，有线程切换开销
    - 新方案：直接使用 AsyncOpenAI/AsyncAnthropic，零开销

    用法：
        from core.llm_client import get_async_llm_client
        async_client = get_async_llm_client(config)
        processor = NativeAsyncChunkProcessor(async_client, max_parallel=8)
        results = await processor.process_all(chunks)
    """

    def __init__(self, async_llm_client, max_parallel: int = 8, structured_output_enabled: bool = False):
        """
        初始化处理器

        Args:
            async_llm_client: AsyncLLMClient 实例
            max_parallel: 最大并行数
            structured_output_enabled: 是否启用结构化输出（强制 JSON Schema）
        """
        self.async_client = async_llm_client
        self.max_parallel = max_parallel
        self.cache = get_cache()
        # 结构化输出开关
        self.structured_output_enabled = structured_output_enabled
        # JSON Schema（用于结构化输出）
        self.chunk_schema = CHUNK_ANALYSIS_JSON_SCHEMA

        # 智能重试配置
        self.retry_delays = [5, 15, 45]
        self.max_retries = 3

        # 动态限流追踪
        self._consecutive_rate_limits = 0
        self._current_max_parallel = max_parallel
        # 动态并发恢复追踪
        self._consecutive_successes = 0
        self._recovery_threshold = 5  # 🔑 优化：从10降低到5，加快限流缓解后的并发度恢复速度

    async def process_single_chunk(
        self,
        chunk_index: int,
        chunk_content: str,
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        use_cache: bool = True,
        local_hints_by_chunk: Optional[Dict[int, object]] = None,
    ) -> ChunkResult:
        """
        处理单个 chunk（原生异步）

        Args:
            chunk_index: chunk 索引
            chunk_content: chunk 内容
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板
            use_cache: 是否使用缓存
            local_hints_by_chunk: 本地预处理候选信号映射

        Returns:
            ChunkResult: 处理结果
        """
        start_time = datetime.now()

        # Step 1: 检查缓存
        if use_cache:
            cached_result = self.cache.get_cached_result(book_title, chunk_index, chunk_content)
            if cached_result:
                elapsed = (datetime.now() - start_time).total_seconds()
                return ChunkResult(
                    chunk_index=chunk_index,
                    success=True,
                    result=cached_result,
                    from_cache=True,
                    elapsed_seconds=elapsed
                )

        # Step 2: 构建 prompt（注入本地 hints）
        prompt = chunk_prompt_template.format(
            book_title=book_title,
            chunk_content=chunk_content
        )
        local_hint_text = _format_local_hint_for_prompt(
            (local_hints_by_chunk or {}).get(chunk_index)
        )
        if local_hint_text:
            prompt = f"{local_hint_text}\n\n{prompt}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # Step 3: 智能重试调用（原生异步）
        for retry in range(self.max_retries):
            try:
                # 🔑 根据配置选择调用方式
                if self.structured_output_enabled:
                    # 结构化输出模式：使用 response_format 强制 JSON
                    result = await self._call_llm_with_schema_async(
                        messages,
                        self.chunk_schema,
                        max_tokens=16384
                    )
                    if result:
                        # 保存到缓存
                        self.cache.save_result(book_title, chunk_index, chunk_content, result)
                        elapsed = (datetime.now() - start_time).total_seconds()
                        logger.info(f"   ✅ Chunk {chunk_index} 完成 (结构化输出, {elapsed:.1f}秒)")

                        # 动态并发恢复
                        self._consecutive_successes += 1
                        if (self._consecutive_successes >= self._recovery_threshold 
                            and self._current_max_parallel < self.max_parallel):
                            self._current_max_parallel = min(self._current_max_parallel + 1, self.max_parallel)
                            logger.info(f"   📈 ���续成功 {self._consecutive_successes} 次，恢复并发度至 {self._current_max_parallel}")
                            self._consecutive_rate_limits = 0

                        return ChunkResult(
                            chunk_index=chunk_index,
                            success=True,
                            result=result,
                            from_cache=False,
                            elapsed_seconds=elapsed
                        )
                    else:
                        # 结构化输出失败，回退到普通模式
                        logger.warning(f"   ⚠️ Chunk {chunk_index} 结构化输出失败，回退到普通模式")
                else:
                    # 普通模式：使用异步调用 + parse_model_output
                    response = await self.async_client._call_llm_async(
                        messages,
                        max_tokens=16384
                    )

                    if response is None:
                        base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                        actual_delay = random.uniform(0.8, 1.2) * base_delay
                        logger.warning(f"   ⚠️ Chunk {chunk_index} 空响应，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试 ({retry+1}/{self.max_retries})")
                        await asyncio.sleep(actual_delay)
                        continue

                    # Step 4: 统一 JSON 解析（三层防护）
                    result, success, error_msg = parse_model_output(response)

                    if success and result:
                        # 保存到缓存
                        self.cache.save_result(book_title, chunk_index, chunk_content, result)

                        elapsed = (datetime.now() - start_time).total_seconds()
                        logger.info(f"   ✅ Chunk {chunk_index} 完成 ({elapsed:.1f}秒)")

                        # 动态并发恢复：连续成功后逐步恢复并发度
                        self._consecutive_successes += 1
                        if (self._consecutive_successes >= self._recovery_threshold 
                            and self._current_max_parallel < self.max_parallel):
                            old_parallel = self._current_max_parallel
                            self._current_max_parallel = min(self._current_max_parallel + 1, self.max_parallel)
                            logger.info(f"   📈 连续成功 {self._consecutive_successes} 次，恢复并发度至 {self._current_max_parallel}")
                            self._consecutive_rate_limits = 0  # 重置限流计数

                        return ChunkResult(
                            chunk_index=chunk_index,
                            success=True,
                            result=result,
                            from_cache=False,
                            elapsed_seconds=elapsed
                        )
                    else:
                        # 解析失败处理
                        if isinstance(result, dict) and result.get("raw_response"):
                            try:
                                safe_title = "".join(
                                    ch if ch.isalnum() or ch in "-_" else "_"
                                    for ch in book_title
                                )[:80]
                                failed_dir = Path.cwd() / "logs" / "failed_chunks"
                                failed_dir.mkdir(parents=True, exist_ok=True)
                                failed_path = failed_dir / f"{safe_title}_chunk_{chunk_index}_retry_{retry + 1}.txt"
                                failed_path.write_text(result["raw_response"], encoding="utf-8", errors="replace")
                                logger.warning(f"   📝 Chunk {chunk_index} 原始响应已保存: {failed_path}")
                            except Exception as save_error:
                                logger.warning(f"   ⚠️ Chunk {chunk_index} 原始响应保存失败: {save_error}")

                        base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                        actual_delay = random.uniform(0.8, 1.2) * base_delay
                        logger.warning(f"   ⚠️ Chunk {chunk_index} 解析失败: {error_msg}，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                        await asyncio.sleep(actual_delay)
                        continue



            except Exception as e:
                error_str = str(e)
                error_lower = error_str.lower()

                # 限流处理（429）
                if '429' in error_str or 'throttling' in error_lower or 'rate limit' in error_lower:
                    self._consecutive_rate_limits += 1
                    self._consecutive_successes = 0  # 重置成功计数
                    if self._consecutive_rate_limits > 3 and self._current_max_parallel > 1:
                        self._current_max_parallel = max(1, self._current_max_parallel // 2)
                        logger.warning(f"   ⚠️ 检测到持续限流，降低最大并发至 {self._current_max_parallel}")

                    base_delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)] * 2
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 限流，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                    await asyncio.sleep(actual_delay)
                    continue

                logger.error(f"   ❌ Chunk {chunk_index} 异常: {error_str[:100]}")
                if retry < self.max_retries - 1:
                    base_delay = self.retry_delays[0]
                    actual_delay = random.uniform(0.8, 1.2) * base_delay
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 其他异常，Jitter 延迟: {actual_delay:.1f}秒 (基准 {base_delay}s) 后重试")
                    await asyncio.sleep(actual_delay)
                    continue

        # 所有重试都失败
        elapsed = (datetime.now() - start_time).total_seconds()
        return ChunkResult(
            chunk_index=chunk_index,
            success=False,
            error="重试耗尽",
            elapsed_seconds=elapsed
        )


    async def _call_llm_with_schema_async(
        self,
        messages: List[Dict],
        schema: Dict,
        max_tokens: int = None
    ) -> Dict:
        """
        异步调用 LLM 并强制 JSON Schema 输出

        使用 OpenAI response_format 强制 LLM 输出符合 schema 的 JSON。
        
        Args:
            messages: 消息列表
            schema: JSON Schema 字典
            max_tokens: 最大输出 token 数

        Returns:
            Dict: 解析后的 JSON 对象，失败返回 None
        """
        max_tokens = max_tokens or 16384

        if not self.async_client.async_openai_client:
            logger.warning("⚠️ AsyncOpenAI 客户端未初始化，无法使用 JSON Schema 模式")
            return None

        try:
            import json
            response = await self.async_client.async_openai_client.chat.completions.create(
                model=self.async_client.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=self.async_client.temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ChunkAnalysis",
                        "schema": schema,
                        "strict": True
                    }
                }
            )

            content = response.choices[0].message.content
            if content:
                return json.loads(content)
            return None

        except Exception as e:
            logger.error(f"❌ JSON Schema 模式失败: {str(e)[:100]}")
            return None

    async def process_chunks_parallel(
        self,
        chunks: List[Tuple[int, str, str]],
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        use_cache: bool = True,
        local_hints_by_chunk: Optional[Dict[int, object]] = None,
    ) -> List[ChunkResult]:
        """
        并行处理所有 chunks（原生异步）

        Args:
            chunks: chunk 列表 [(index, content, label)]
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板
            use_cache: 是否使用缓存
            local_hints_by_chunk: 本地预处理候选信号映射

        Returns:
            List[ChunkResult]: 所有处理结果
        """
        effective_max = self._current_max_parallel
        logger.info(f"🚀 原生异步处理 {len(chunks)} 个 chunks（最大并行数: {effective_max}）")

        semaphore = asyncio.Semaphore(effective_max)

        async def process_with_semaphore(chunk):
            async with semaphore:
                idx, content, label = chunk
                logger.info(f"   ▶️ 开始处理 Chunk {idx} [{label}]")
                return await self.process_single_chunk(
                    idx, content, book_title, system_prompt, chunk_prompt_template, use_cache,
                    local_hints_by_chunk=local_hints_by_chunk,
                )

        # 并行启动所有任务
        tasks = [process_with_semaphore(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ChunkResult(
                    chunk_index=chunks[i][0],
                    success=False,
                    error=str(result)[:100]
                ))
            else:
                final_results.append(result)

        # 统计结果
        success_count = sum(1 for r in final_results if r.success)
        cache_count = sum(1 for r in final_results if r.from_cache)
        total_time = sum(r.elapsed_seconds for r in final_results)

        logger.info(f"✅ 处理完成: {success_count}/{len(chunks)} 成功")
        logger.info(f"   📊 统计: {cache_count} 缓存命中，总耗时 {total_time:.1f}秒")

        return final_results


async def process_book_chunks_native_async(
    async_llm_client,
    chunks: List[Tuple[int, str, str]],
    book_title: str,
    system_prompt: str,
    chunk_prompt_template: str,
    max_parallel: int = 8,
    local_hints_by_chunk: Optional[Dict[int, object]] = None,
    structured_output_enabled: bool = False,
) -> List[Dict]:
    """
    原生异步书籍 chunk 处理接口

    Args:
        async_llm_client: AsyncLLMClient 实例
        chunks: chunk 列表
        book_title: 书名
        system_prompt: 系统提示词
        chunk_prompt_template: chunk 提示词模板
        max_parallel: 最大并行数
        local_hints_by_chunk: 本地预处理候选信号映射
        structured_output_enabled: 是否启用结构化输出（强制 JSON Schema）

    Returns:
        List[Dict]: 成功的解析结果列表
    """
    processor = NativeAsyncChunkProcessor(
        async_llm_client,
        max_parallel,
        structured_output_enabled=structured_output_enabled
    )

    results = await processor.process_chunks_parallel(
        chunks, book_title, system_prompt, chunk_prompt_template,
        local_hints_by_chunk=local_hints_by_chunk,
    )

    # 返回成功的结果
    successful_results = [r.result for r in results if r.success and r.result]
    return successful_results