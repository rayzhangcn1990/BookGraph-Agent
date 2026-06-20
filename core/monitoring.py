"""
BookGraph-Agent Prometheus 监控集成

提供性能指标监控、任务执行追踪、资源使用统计
"""

import logging
from typing import Dict, List
from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry
from prometheus_client.openmetrics.exposition import generate_latest
import time

logger = logging.getLogger("BookGraph-Agent")

# ═══════════════════════════════════════════════════════════
# Prometheus 指标定义
# ═══════════════════════════════════════════════════════════

# 创建注册表
registry = CollectorRegistry()

# API 请求计数
API_REQUEST_COUNT = Counter(
    'bookgraph_api_requests_total',
    'Total number of API requests',
    ['method', 'endpoint', 'status'],
    registry=registry
)

# API 请求延迟
API_REQUEST_LATENCY = Histogram(
    'bookgraph_api_request_latency_seconds',
    'API request latency in seconds',
    ['method', 'endpoint'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=registry
)

# 任务计数
TASK_COUNT = Counter(
    'bookgraph_tasks_total',
    'Total number of tasks',
    ['status', 'phase'],
    registry=registry
)

# 任务执行时长
TASK_DURATION = Histogram(
    'bookgraph_task_duration_seconds',
    'Task execution duration in seconds',
    ['phase'],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    registry=registry
)

# 活跃任务数
ACTIVE_TASKS = Gauge(
    'bookgraph_active_tasks',
    'Number of currently active tasks',
    ['phase'],
    registry=registry
)

# LLM 调用计数
LLM_CALL_COUNT = Counter(
    'bookgraph_llm_calls_total',
    'Total number of LLM API calls',
    ['model', 'status'],
    registry=registry
)

# LLM 调用延迟
LLM_CALL_LATENCY = Histogram(
    'bookgraph_llm_call_latency_seconds',
    'LLM API call latency in seconds',
    ['model'],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=registry
)

# LLM Token 使用量
LLM_TOKEN_USAGE = Counter(
    'bookgraph_llm_tokens_total',
    'Total number of tokens used',
    ['model', 'type'],  # type: input/output
    registry=registry
)

# Chunk 处理计数
CHUNK_PROCESS_COUNT = Counter(
    'bookgraph_chunks_processed_total',
    'Total number of chunks processed',
    ['status'],
    registry=registry
)

# Chunk 处理时长
CHUNK_PROCESS_LATENCY = Histogram(
    'bookgraph_chunk_process_latency_seconds',
    'Chunk processing latency in seconds',
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0],
    registry=registry
)

# 缓存命中率
CACHE_HIT_RATE = Gauge(
    'bookgraph_cache_hit_rate',
    'Cache hit rate (0-1)',
    ['cache_type'],
    registry=registry
)

# 并发度
CONCURRENCY_LEVEL = Gauge(
    'bookgraph_concurrency_level',
    'Current concurrency level',
    ['type'],
    registry=registry
)

# 质量门控通过率
QUALITY_GATE_PASS_RATE = Gauge(
    'bookgraph_quality_gate_pass_rate',
    'Quality gate pass rate (0-1)',
    registry=registry
)

# 系统信息
SYSTEM_INFO = Info(
    'bookgraph_system',
    'BookGraph-Agent system information',
    registry=registry
)
SYSTEM_INFO.info({
    'version': '1.0.0',
    'python_version': '3.11',
    'llm_provider': 'openai'
})


# ═══════════════════════════════════════════════════════════
# 监控中间件
# ═══════════════════════════════════════════════════════════

class PrometheusMiddleware:
    """FastAPI Prometheus 监控中间件"""

    def __init__(self, app):
        """初始化中间件"""
        self.app = app

    async def __call__(self, scope, receive, send):
        """拦截请求并记录指标"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]

        # 排除监控端点
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        status_code = 500

        # 包装 send 函数以捕获状态码
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # 记录指标
            latency = time.time() - start_time

            API_REQUEST_COUNT.labels(
                method=method,
                endpoint=path,
                status=status_code
            ).inc()

            API_REQUEST_LATENCY.labels(
                method=method,
                endpoint=path
            ).observe(latency)


# ═══════════════════════════════════════════════════════════
# 监控工具函数
# ═══════════════════════════════════════════════════════════

def track_task_start(phase: str):
    """追踪任务开始"""
    ACTIVE_TASKS.labels(phase=phase).inc()
    TASK_COUNT.labels(status='started', phase=phase).inc()


def track_task_end(phase: str, duration: float, success: bool = True):
    """追踪任务结束"""
    ACTIVE_TASKS.labels(phase=phase).dec()
    TASK_COUNT.labels(status='completed' if success else 'failed', phase=phase).inc()
    TASK_DURATION.labels(phase=phase).observe(duration)


def track_llm_call(model: str, duration: float, success: bool = True, tokens_in: int = 0, tokens_out: int = 0):
    """追踪 LLM 调用"""
    status = 'success' if success else 'failed'

    LLM_CALL_COUNT.labels(model=model, status=status).inc()
    LLM_CALL_LATENCY.labels(model=model).observe(duration)

    if tokens_in > 0:
        LLM_TOKEN_USAGE.labels(model=model, type='input').inc(tokens_in)
    if tokens_out > 0:
        LLM_TOKEN_USAGE.labels(model=model, type='output').inc(tokens_out)


def track_chunk_process(duration: float, success: bool = True, from_cache: bool = False):
    """追踪 Chunk 处理"""
    status = 'cache_hit' if from_cache else ('success' if success else 'failed')

    CHUNK_PROCESS_COUNT.labels(status=status).inc()
    if not from_cache:
        CHUNK_PROCESS_LATENCY.observe(duration)


def update_cache_hit_rate(cache_type: str, hit_rate: float):
    """更新缓存命中率"""
    CACHE_HIT_RATE.labels(cache_type=cache_type).set(hit_rate)


def update_concurrency_level(concurrency_type: str, level: int):
    """更新并发度"""
    CONCURRENCY_LEVEL.labels(type=concurrency_type).set(level)


def update_quality_gate_pass_rate(pass_rate: float):
    """更新质量门控通过率"""
    QUALITY_GATE_PASS_RATE.set(pass_rate)


def get_metrics() -> str:
    """获取 Prometheus 指标（OpenMetrics 格式）"""
    return generate_latest(registry).decode('utf-8')


# ═══════════════════════════════════════════════════════════
# FastAPI 集成
# ═══════════════════════════════════════════════════════════

def setup_prometheus(app):
    """
    为 FastAPI 应用设置 Prometheus 监控

    Args:
        app: FastAPI 应用实例
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    # 添加监控中间件
    app.add_middleware(BaseHTTPMiddleware, dispatch=PrometheusMiddleware(app))

    # 添加 /metrics 端点
    @app.get("/metrics")
    async def metrics():
        """Prometheus 指标端点"""
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            get_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    logger.info("Prometheus 监控已启用: /metrics")


# ═══════════════════════════════════════════════════════════
# 仪表盘配置示例
# ═══════════════════════════════════════════════════════════

GRAFANA_DASHBOARD_JSON = """
{
  "dashboard": {
    "title": "BookGraph-Agent Monitoring",
    "panels": [
      {
        "title": "API Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(bookgraph_api_requests_total[5m])",
            "legendFormat": "{{method}} {{endpoint}}"
          }
        ]
      },
      {
        "title": "API Latency (p95)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(bookgraph_api_request_latency_seconds_bucket[5m]))",
            "legendFormat": "p95 latency"
          }
        ]
      },
      {
        "title": "Task Success Rate",
        "type": "gauge",
        "targets": [
          {
            "expr": "sum(rate(bookgraph_tasks_total{status=\\"completed\\"}[5m])) / sum(rate(bookgraph_tasks_total[5m]))",
            "legendFormat": "success rate"
          }
        ]
      },
      {
        "title": "LLM Call Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(bookgraph_llm_calls_total[5m])",
            "legendFormat": "{{model}} {{status}}"
          }
        ]
      },
      {
        "title": "Token Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(bookgraph_llm_tokens_total[5m])",
            "legendFormat": "{{model}} {{type}}"
          }
        ]
      },
      {
        "title": "Cache Hit Rate",
        "type": "gauge",
        "targets": [
          {
            "expr": "bookgraph_cache_hit_rate",
            "legendFormat": "{{cache_type}}"
          }
        ]
      },
      {
        "title": "Quality Gate Pass Rate",
        "type": "gauge",
        "targets": [
          {
            "expr": "bookgraph_quality_gate_pass_rate",
            "legendFormat": "pass rate"
          }
        ]
      }
    ]
  }
}
"""
