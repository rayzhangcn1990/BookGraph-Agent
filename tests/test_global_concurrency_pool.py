#!/usr/bin/env python3
"""
全局并发池测试

验证 P0 优化：全局并发池装饰器功能
"""

import asyncio
import pytest
from core.global_concurrency_pool import (
    GlobalConcurrencyPool,
    limit_concurrency,
    get_concurrency_pool,
    configure_global_pool,
    get_concurrency_stats
)


def test_global_concurrency_pool_init():
    """测试全局并发池初始化"""
    pool = GlobalConcurrencyPool(max_workers=4)

    assert pool.max_workers == 4
    assert pool.active_tasks == 0
    assert pool.rate_limit_hits == 0


def test_get_concurrency_pool_singleton():
    """测试单例模式"""
    pool1 = get_concurrency_pool(max_workers=4)
    pool2 = get_concurrency_pool()

    assert pool1 is pool2


def test_configure_global_pool():
    """测试配置更新"""
    pool = get_concurrency_pool(max_workers=4)
    configure_global_pool(8)

    assert pool.max_workers == 8


@pytest.mark.asyncio
async def test_limit_concurrency_decorator():
    """测试并发限制装饰器"""

    @limit_concurrency
    async def mock_llm_call(prompt: str):
        await asyncio.sleep(0.1)
        return f"response: {prompt}"

    # 并发调用（不超过限制）
    tasks = [mock_llm_call(f"prompt_{i}") for i in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all("response" in r for r in results)


@pytest.mark.asyncio
async def test_rate_limit_detection():
    """测试限流检测"""
    pool = get_concurrency_pool()

    @limit_concurrency
    async def mock_llm_call_with_rate_limit():
        raise Exception("429 - rate limit exceeded")

    try:
        await mock_llm_call_with_rate_limit()
    except Exception:
        pass

    # 应该记录了限流事件
    stats = get_concurrency_stats()
    assert stats.rate_limit_hits > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
