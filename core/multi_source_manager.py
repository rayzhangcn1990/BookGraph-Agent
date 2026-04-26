"""
多API源管理器
- 支持多个API供应商（额度独立）
- 当一个API额度耗尽时自动切换到下一个
- 管理API源优先级和配额
"""

import os
import logging
import httpx
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class APISource:
    name: str
    api_base: str
    api_key: str
    priority: int
    quota_type: str  # shared / independent
    is_exhausted: bool = False
    request_count: int = 0
    extra_headers: Dict = None  # 额外请求头（如 OpenRouter 需要）


class MultiSourceAPIManager:
    """多API源管理器"""

    def __init__(self, config: Dict):
        """
        Args:
            config: llm配置部分，包含 api_sources 列表
        """
        self.sources: List[APISource] = []
        self.current_source: Optional[APISource] = None
        self.shared_quota_exhausted: bool = False  # 共享额度状态

        # 初始化API源
        self._init_sources(config)

    def _init_sources(self, config: Dict):
        """初始化API源列表"""
        api_sources_config = config.get("api_sources", [])

        for source_config in api_sources_config:
            # 处理环境变量
            api_key = source_config.get("api_key", "unused")
            if api_key.startswith("${") and api_key.endswith("}"):
                env_var = api_key[2:-1]
                api_key = os.environ.get(env_var, "")

            # 跳过无有效API key的源（除非是本地服务）
            if not api_key and "localhost" not in source_config.get("api_base", ""):
                continue

            source = APISource(
                name=source_config.get("name", "unknown"),
                api_base=source_config.get("api_base", ""),
                api_key=api_key,
                priority=source_config.get("priority", 99),
                quota_type=source_config.get("quota_type", "shared"),
                extra_headers=source_config.get("extra_headers", {}),
            )
            self.sources.append(source)

        # 按优先级排序
        self.sources.sort(key=lambda s: s.priority)

        # 选择第一个可用源
        if self.sources:
            self.current_source = self.sources[0]
            logger.info(f"📋 API源列表: {len(self.sources)} 个")
            for s in self.sources:
                logger.info(f"   {s.priority}. {s.name} ({s.quota_type})")

    def get_current_source(self) -> Optional[APISource]:
        """获取当前API源"""
        return self.current_source

    def switch_to_next_source(self, reason: str = ""):
        """切换到下一个可用API源"""
        if not self.current_source:
            return False

        # 标记当前源为耗尽
        self.current_source.is_exhausted = True

        # 如果是共享额度，标记全局状态
        if self.current_source.quota_type == "shared":
            self.shared_quota_exhausted = True
            logger.warning(f"⚠️ 共享额度耗尽 ({self.current_source.name})")

        # 找下一个可用源
        for source in self.sources:
            # 跳过耗尽的源
            if source.is_exhausted:
                continue

            # 跳过共享额度耗尽的源（如果已耗尽）
            if source.quota_type == "shared" and self.shared_quota_exhausted:
                continue

            # 找到可用源
            self.current_source = source
            logger.info(f"🔄 切换到API源: {source.name}")
            logger.info(f"   API Base: {source.api_base}")
            return True

        # 所有源都耗尽
        logger.warning("⚠️ 所有API源额度耗尽")
        return False

    def get_available_sources_count(self) -> int:
        """获取可用源数量"""
        count = 0
        for source in self.sources:
            if source.is_exhausted:
                continue
            if source.quota_type == "shared" and self.shared_quota_exhausted:
                continue
            count += 1
        return count

    def mark_request(self, success: bool):
        """记录请求结果"""
        if self.current_source:
            self.current_source.request_count += 1
            # 成功/失败记录，不立即切换

    def reset_shared_quota(self):
        """重置共享额度（新的一天）"""
        self.shared_quota_exhausted = False
        for source in self.sources:
            if source.quota_type == "shared":
                source.is_exhausted = False

    def reset_all(self):
        """重置所有源（完全重置）"""
        self.shared_quota_exhausted = False
        for source in self.sources:
            source.is_exhausted = False
            source.request_count = 0


def create_client_from_source(source: APISource) -> Optional[object]:
    """从API源创建OpenAI客户端"""
    try:
        import openai

        # 构建默认头
        default_headers = {}
        if source.extra_headers:
            default_headers.update(source.extra_headers)

        # OpenRouter 需要特殊头
        if "openrouter" in source.name.lower() or "openrouter" in source.api_base.lower():
            default_headers.setdefault("HTTP-Referer", "https://bookgraph.app")
            default_headers.setdefault("X-Title", "BookGraph-Agent")

        client = openai.OpenAI(
            api_key=source.api_key or "unused",
            base_url=source.api_base,
            timeout=600,
            default_headers=default_headers if default_headers else None,
        )
        return client
    except Exception as e:
        logger.error(f"创建客户端失败 ({source.name}): {e}")
        return None


async def test_source_availability(source: APISource) -> bool:
    """测试API源可用性"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{source.api_base}/v1/models",
                headers={"x-api-key": source.api_key}
            )
            return response.status_code == 200
    except Exception as e:
        logger.warning(f"API源 {source.name} 不可用: {e}")
        return False