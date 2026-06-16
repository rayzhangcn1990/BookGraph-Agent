"""
全局并发池管理器

基于 nano-graphrag 的 limit_async_func_call 装饰器模式实现。
控制总并发数，避免API限流。

核心功能：
1. 全局并发池（替代每书独立并发）
2. limit_async_func_call 装饰器
3. 动态并发度调整（根据限流状态自适应）
"""

import asyncio
import logging
from functools import wraps
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ConcurrencyStats:
    """并发统计"""
    active_tasks: int
    total_tasks: int
    rate_limit_hits: int
    last_rate_limit_time: Optional[datetime]


class GlobalConcurrencyPool:
    """
    全局并发池管理器

    单例模式，控制所有LLM调用的总并发数。

    使用方法：
    ```python
    from core.global_concurrency_pool import get_concurrency_pool, limit_concurrency

    # 方式1：装饰器模式
    @limit_concurrency
    async def call_llm(prompt):
        return await llm_client.generate(prompt)

    # 方式2：上下文管理器
    async def call_llm(prompt):
        pool = get_concurrency_pool()
        async with pool.acquire():
            return await llm_client.generate(prompt)
    ```
    """

    _instance: Optional['GlobalConcurrencyPool'] = None

    def __init__(self, max_workers: int = 4):
        """
        初始化全局并发池

        Args:
            max_workers: 最大并发数（默认4，可从config.yaml覆盖）
        """
        self.semaphore = asyncio.Semaphore(max_workers)
        self.max_workers = max_workers

        # 统计信息
        self.active_tasks = 0
        self.total_tasks = 0
        self.rate_limit_hits = 0
        self.last_rate_limit_time: Optional[datetime] = None

        # 动态调整
        self._consecutive_rate_limits = 0
        self._current_max_parallel = max_workers
        self._consecutive_successes = 0
        self._recovery_threshold = 10  # 连续成功10次后恢复并发度

    @classmethod
    def get_instance(cls, max_workers: int = 4) -> 'GlobalConcurrencyPool':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(max_workers)
        return cls._instance

    def configure(self, max_workers: int):
        """
        配置最大并发数

        Args:
            max_workers: 最大并发数
        """
        if max_workers != self.max_workers:
            logger.info(f"全局并发池配置更新: {self.max_workers} → {max_workers}")
            self.semaphore = asyncio.Semaphore(max_workers)
            self.max_workers = max_workers
            self._current_max_parallel = max_workers

    async def acquire(self):
        """
        获取并发槽位

        Returns:
            asyncio.Semaphore: 信号量上下文管理器
        """
        return self.semaphore.acquire()

    def get_stats(self) -> ConcurrencyStats:
        """获取并发统计信息"""
        return ConcurrencyStats(
            active_tasks=self.active_tasks,
            total_tasks=self.total_tasks,
            rate_limit_hits=self.rate_limit_hits,
            last_rate_limit_time=self.last_rate_limit_time
        )

    def record_task_start(self):
        """记录任务开始"""
        self.active_tasks += 1
        self.total_tasks += 1

    def record_task_end(self):
        """记录任务结束"""
        self.active_tasks -= 1

    def record_rate_limit(self):
        """记录限流事件"""
        self.rate_limit_hits += 1
        self.last_rate_limit_time = datetime.now()
        self._consecutive_rate_limits += 1
        self._consecutive_successes = 0

        # 动态降低并发度（避免触发更多限流）
        if self._consecutive_rate_limits >= 2:
            new_parallel = max(1, self._current_max_parallel - 1)
            if new_parallel < self._current_max_parallel:
                logger.warning(
                    f"检测到连续限流，动态降低并发度: "
                    f"{self._current_max_parallel} → {new_parallel}"
                )
                self._current_max_parallel = new_parallel
                self.semaphore = asyncio.Semaphore(new_parallel)

    def record_success(self):
        """记录成功完成"""
        self._consecutive_successes += 1
        self._consecutive_rate_limits = 0

        # 连续成功多次后，尝试恢复并发度
        if (
            self._consecutive_successes >= self._recovery_threshold
            and self._current_max_parallel < self.max_workers
        ):
            new_parallel = min(self.max_workers, self._current_max_parallel + 1)
            if new_parallel > self._current_max_parallel:
                logger.info(
                    f"连续成功{self._consecutive_successes}次，恢复并发度: "
                    f"{self._current_max_parallel} → {new_parallel}"
                )
                self._current_max_parallel = new_parallel
                self.semaphore = asyncio.Semaphore(new_parallel)
                self._consecutive_successes = 0


# ═══════════════════════════════════════════════════════════
# 装饰器
# ═══════════════════════════════════════════════════════════

def limit_concurrency(func: Callable):
    """
    并发限制装饰器

    使用方法：
    ```python
    @limit_concurrency
    async def call_llm(prompt):
        return await llm_client.generate(prompt)
    ```

    效果：
    - 自动获取并发槽位
    - 记录任务统计信息
    - 异常时自动释放槽位
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        pool = get_concurrency_pool()

        async with pool.semaphore:
            pool.record_task_start()
            try:
                result = await func(*args, **kwargs)
                pool.record_success()
                return result
            except Exception as e:
                # 检测是否为限流错误
                error_str = str(e).lower()
                if '429' in error_str or 'rate' in error_str or 'limit' in error_str:
                    pool.record_rate_limit()
                    logger.warning(f"检测到API限流: {e}")
                raise
            finally:
                pool.record_task_end()

    return wrapper


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_pool: Optional[GlobalConcurrencyPool] = None


def get_concurrency_pool(max_workers: int = 4) -> GlobalConcurrencyPool:
    """
    获取全局并发池单例

    Args:
        max_workers: 最大并发数（首次调用时生效）

    Returns:
        GlobalConcurrencyPool: 全局并发池实例
    """
    global _pool
    if _pool is None:
        _pool = GlobalConcurrencyPool.get_instance(max_workers)
    return _pool


def configure_global_pool(max_workers: int):
    """
    配置全局并发池

    Args:
        max_workers: 最大并发数
    """
    pool = get_concurrency_pool()
    pool.configure(max_workers)


def get_concurrency_stats() -> ConcurrencyStats:
    """获取并发统计信息"""
    pool = get_concurrency_pool()
    return pool.get_stats()
