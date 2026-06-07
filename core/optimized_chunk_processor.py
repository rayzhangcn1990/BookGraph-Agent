"""
优化版 Chunk 并行处理器

核心优化点：
1. asyncio 并行处理（替代 ThreadPoolExecutor）
2. 智能重试策略（30→60→90秒指数退避）
3. 缓存机制（断点续传）
4. 统一 JSON 解析（三层防护）
5. 全局客户端复用（避免重复初始化）
"""

import asyncio
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

logger = logging.getLogger("BookGraph-Agent")


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
        self.retry_delays = [30, 60, 90]  # 指数退避（秒）
        self.max_retries = 3
        # 动态限流追踪
        self._consecutive_rate_limits = 0
        self._current_max_parallel = max_parallel

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
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 空响应，{delay}秒后重试 ({retry+1}/{self.max_retries})")
                    await asyncio.sleep(delay)
                    continue

                # Step 4: 统一 JSON 解析（三层防护）
                result, success, error_msg = parse_model_output(response)

                if success and result:
                    # 保存到缓存
                    self.cache.save_result(book_title, chunk_index, chunk_content, result)

                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   ✅ Chunk {chunk_index} 完成 ({elapsed:.1f}秒)")

                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=result,
                        from_cache=False,
                        elapsed_seconds=elapsed
                    )
                else:
                    # 解析失败，等待后重试
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 解析失败: {error_msg}，{delay}秒后重试")
                    await asyncio.sleep(delay)

            except Exception as e:
                # 异常处理
                error_str = str(e)
                error_lower = error_str.lower()

                # 限流处理（429）
                if '429' in error_str or 'throttling' in error_lower or 'rate limit' in error_lower:
                    self._consecutive_rate_limits += 1
                    # 动态降低并发度
                    if self._consecutive_rate_limits > 3 and self._current_max_parallel > 1:
                        self._current_max_parallel = max(1, self._current_max_parallel // 2)
                        logger.warning(f"   ⚠️ 检测到持续限流，降低最大并发至 {self._current_max_parallel}")
                        # 更新信号量（将在下次 process_chunks_parallel 重新创建）
                    # 指数退避，并尝试解析 Retry-After
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)] * 2
                    # 尝试从错误消息中提取等待秒数
                    import re
                    match = re.search(r'retry after (\d+)', error_str)
                    if match:
                        delay = int(match.group(1))
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 限流，{delay}秒后重试")
                    await asyncio.sleep(delay)
                    continue

                # 其他异常
                logger.error(f"   ❌ Chunk {chunk_index} 异常: {error_str[:100]}")
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delays[0])
                    continue

        # 所有重试都失败
        elapsed = (datetime.now() - start_time).total_seconds()
        return ChunkResult(
            chunk_index=chunk_index,
            success=False,
            error="重试耗尽",
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

    def __init__(self, async_llm_client, max_parallel: int = 8):
        """
        初始化处理器

        Args:
            async_llm_client: AsyncLLMClient 实例
            max_parallel: 最大并行数
        """
        self.async_client = async_llm_client
        self.max_parallel = max_parallel
        self.cache = get_cache()

        # 智能重试配置
        self.retry_delays = [30, 60, 90]
        self.max_retries = 3

        # 动态限流追踪
        self._consecutive_rate_limits = 0
        self._current_max_parallel = max_parallel

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
        处理单个 chunk（原生异步）

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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # Step 3: 智能重试调用（原生异步）
        for retry in range(self.max_retries):
            try:
                # 🔑 关键：使用原生异步调用
                response = await self.async_client._call_llm_async(
                    messages,
                    max_tokens=16384
                )

                if response is None:
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 空响应，{delay}秒后重试 ({retry+1}/{self.max_retries})")
                    await asyncio.sleep(delay)
                    continue

                # Step 4: 统一 JSON 解析
                result, success, error_msg = parse_model_output(response)

                if success and result:
                    # 保存到缓存
                    self.cache.save_result(book_title, chunk_index, chunk_content, result)

                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"   ✅ Chunk {chunk_index} 完成 ({elapsed:.1f}秒)")

                    return ChunkResult(
                        chunk_index=chunk_index,
                        success=True,
                        result=result,
                        from_cache=False,
                        elapsed_seconds=elapsed
                    )
                else:
                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)]
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 解析失败: {error_msg}，{delay}秒后重试")
                    await asyncio.sleep(delay)

            except Exception as e:
                error_str = str(e)
                error_lower = error_str.lower()

                # 限流处理（429）
                if '429' in error_str or 'throttling' in error_lower or 'rate limit' in error_lower:
                    self._consecutive_rate_limits += 1
                    if self._consecutive_rate_limits > 3 and self._current_max_parallel > 1:
                        self._current_max_parallel = max(1, self._current_max_parallel // 2)
                        logger.warning(f"   ⚠️ 检测到持续限流，降低最大并发至 {self._current_max_parallel}")

                    delay = self.retry_delays[min(retry, len(self.retry_delays) - 1)] * 2
                    logger.warning(f"   ⚠️ Chunk {chunk_index} 限流，{delay}秒后重试")
                    await asyncio.sleep(delay)
                    continue

                logger.error(f"   ❌ Chunk {chunk_index} 异常: {error_str[:100]}")
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delays[0])
                    continue

        # 所有重试都失败
        elapsed = (datetime.now() - start_time).total_seconds()
        return ChunkResult(
            chunk_index=chunk_index,
            success=False,
            error="重试耗尽",
            elapsed_seconds=elapsed
        )

    async def process_chunks_parallel(
        self,
        chunks: List[Tuple[int, str, str]],
        book_title: str,
        system_prompt: str,
        chunk_prompt_template: str,
        use_cache: bool = True
    ) -> List[ChunkResult]:
        """
        并行处理所有 chunks（原生异步）

        Args:
            chunks: chunk 列表 [(index, content, label)]
            book_title: 书名
            system_prompt: 系统提示词
            chunk_prompt_template: chunk 提示词模板
            use_cache: 是否使用缓存

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


async def process_book_chunks_native_async(
    async_llm_client,
    chunks: List[Tuple[int, str, str]],
    book_title: str,
    system_prompt: str,
    chunk_prompt_template: str,
    max_parallel: int = 8
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

    Returns:
        List[Dict]: 成功的解析结果列表
    """
    processor = NativeAsyncChunkProcessor(async_llm_client, max_parallel)

    results = await processor.process_chunks_parallel(
        chunks, book_title, system_prompt, chunk_prompt_template
    )

    # 返回成功的结果
    successful_results = [r.result for r in results if r.success and r.result]
    return successful_results