"""异步 LLM 客户端回归测试。"""

from core.llm_client import AsyncLLMClient




def test_async_client_exposes_api_base_from_config():
    """异步客户端应保留 api_base，避免错误日志二次失败。"""
    config = {
        "provider": "openai",
        "model": "test-model",
        "api_base": "http://localhost:3001/v1",
        "api_key": "test-key",
    }

    client = AsyncLLMClient(config)

    assert client.api_base == "http://localhost:3001/v1"


def test_async_client_accepts_root_config_llm_section():
    """异步客户端接收根配置时，应使用 llm 子配置。"""
    config = {
        "llm": {
            "provider": "openai",
            "model": "deepseek/deepseek-chat",
            "api_base": "http://localhost:3001/v1",
            "api_key": "test-key",
        }
    }

    client = AsyncLLMClient(config)

    assert client.provider == "openai"
    assert client.model == "deepseek/deepseek-chat"
    assert client.api_base == "http://localhost:3001/v1"
