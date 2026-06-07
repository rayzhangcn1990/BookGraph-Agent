"""
集成 instructor 实现零报错结构化输出

关键学习点：
1. 使用 Pydantic 模型作为返回类型
2. 自动重试失败的验证
3. 多 provider 支持（OpenAI/Anthropic/本地模型）
4. 流式输出支持

参考：https://github.com/jxnl/instructor
"""

import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("BookGraph-Agent")

# 尝试导入 instructor
try:
    import instructor
    from instructor import Mode
    INSTRUCTOR_AVAILABLE = True
except ImportError:
    INSTRUCTOR_AVAILABLE = False
    logger.info("instructor 未安装，使用内置结构化输出。安装: pip install instructor")


T = TypeVar("T", bound=BaseModel)


# ═══════════════════════════════════════════════════════════
# Instructor 集成封装
# ═══════════════════════════════════════════════════════════

class InstructorWrapper:
    """
    Instructor 封装器

    功能：
    - 统一的结构化输出接口
    - 自动重试失败的验证
    - 多 provider 支持
    - 回退到内置 JSON Schema 模式

    参考：https://github.com/jxnl/instructor
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        初始化 Instructor 封装器

        Args:
            provider: 提供商（openai/anthropic/ollama）
            model: 模型名称
            api_key: API Key
            base_url: API 基础 URL
        """
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

        self._client = None
        self._instructor_client = None

        if INSTRUCTOR_AVAILABLE:
            self._init_instructor_client()

    def _init_instructor_client(self):
        """初始化 Instructor 客户端"""
        try:
            if self.provider == "openai":
                from openai import OpenAI
                client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                self._instructor_client = instructor.from_openai(
                    client,
                    mode=Mode.TOOLS,  # 使用 function calling 模式
                )
                logger.info("✅ Instructor OpenAI 客户端初始化成功")

            elif self.provider == "anthropic":
                from anthropic import Anthropic
                client = Anthropic(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                self._instructor_client = instructor.from_anthropic(
                    client,
                    mode=Mode.ANTHROPIC_TOOLS,
                )
                logger.info("✅ Instructor Anthropic 客户端初始化成功")

            else:
                logger.warning(f"⚠️ 不支持的 provider: {self.provider}")

        except Exception as e:
            logger.warning(f"⚠️ Instructor 初始化失败: {e}")
            self._instructor_client = None

    def extract(
        self,
        response_model: Type[T],
        messages: List[Dict],
        max_retries: int = 3,
        **kwargs,
    ) -> Optional[T]:
        """
        从 LLM 响应中提取结构化数据

        Args:
            response_model: Pydantic 模型类
            messages: 消息列表
            max_retries: 最大重试次数
            **kwargs: 其他参数

        Returns:
            Optional[T]: 提取的结构化对象
        """
        if not INSTRUCTOR_AVAILABLE:
            logger.warning("⚠️ instructor 不可用，使用回退模式")
            return self._fallback_extract(response_model, messages, **kwargs)

        if not self._instructor_client:
            logger.warning("⚠️ Instructor 客户端未初始化，使用回退模式")
            return self._fallback_extract(response_model, messages, **kwargs)

        try:
            # 使用 Instructor 提取
            result = self._instructor_client.chat.completions.create(
                model=self.model,
                response_model=response_model,
                messages=messages,
                max_retries=max_retries,
                **kwargs,
            )
            logger.info(f"✅ Instructor 提取成功: {response_model.__name__}")
            return result

        except Exception as e:
            logger.error(f"❌ Instructor 提取失败: {str(e)[:100]}")
            return None

    async def aextract(
        self,
        response_model: Type[T],
        messages: List[Dict],
        max_retries: int = 3,
        **kwargs,
    ) -> Optional[T]:
        """
        异步提取结构化数据

        Args:
            response_model: Pydantic 模型类
            messages: 消息列表
            max_retries: 最大重试次数
            **kwargs: 其他参数

        Returns:
            Optional[T]: 提取的结构化对象
        """
        if not INSTRUCTOR_AVAILABLE:
            return self._fallback_extract(response_model, messages, **kwargs)

        # 使用 asyncio.to_thread 包装同步调用
        import asyncio
        return await asyncio.to_thread(
            self.extract,
            response_model,
            messages,
            max_retries,
            **kwargs,
        )

    def _fallback_extract(
        self,
        response_model: Type[T],
        messages: List[Dict],
        **kwargs,
    ) -> Optional[T]:
        """
        回退模式：使用内置 JSON Schema 提取

        当 Instructor 不可用时使用
        """
        from core.llm_client import LLMClient
        from schemas.book_graph_schema import BOOK_GRAPH_JSON_SCHEMA

        # 构建带 Schema 提示的 prompt
        schema = response_model.model_json_schema()
        schema_hint = f"\n\n你必须输出严格的 JSON 对象，符合以下 JSON Schema:\n```json\n{schema}\n```"

        # 修改最后一条消息
        modified_messages = list(messages)
        if modified_messages and modified_messages[-1]['role'] == 'user':
            modified_messages[-1]['content'] += schema_hint
        else:
            modified_messages.append({'role': 'user', 'content': schema_hint})

        try:
            # 使用 LLMClient 的 _call_llm_with_schema 方法
            config = {
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "api_base": self.base_url,
            }
            client = LLMClient(config)

            if hasattr(client, '_call_llm_with_schema'):
                result = client._call_llm_with_schema(
                    modified_messages,
                    schema,
                    max_tokens=kwargs.get('max_tokens', 8192),
                )
                return response_model.model_validate(result)
            else:
                # 最终回退：普通 LLM 调用 + 手动解析
                response = client._call_llm(modified_messages)
                if response:
                    import json
                    result = json.loads(response)
                    return response_model.model_validate(result)

        except Exception as e:
            logger.error(f"❌ 回退提取失败: {str(e)[:100]}")

        return None


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_instructor_wrapper: Optional[InstructorWrapper] = None


def get_instructor_wrapper(
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> InstructorWrapper:
    """获取全局 Instructor 封装器单例"""
    global _instructor_wrapper
    if _instructor_wrapper is None:
        _instructor_wrapper = InstructorWrapper(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
    return _instructor_wrapper


async def extract_with_instructor(
    response_model: Type[T],
    messages: List[Dict],
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    **kwargs,
) -> Optional[T]:
    """
    使用 Instructor 提取结构化数据（便捷函数）

    Args:
        response_model: Pydantic 模型类
        messages: 消息列表
        provider: 提供商
        model: 模型名称
        **kwargs: 其他参数

    Returns:
        Optional[T]: 提取的结构化对象
    """
    wrapper = get_instructor_wrapper(provider=provider, model=model)
    return await wrapper.aextract(response_model, messages, **kwargs)


# ═══════════════════════════════════════════════════════════
# BookGraph-Agent 集成
# ═══════════════════════════════════════════════════════════

async def extract_book_graph_with_instructor(
    messages: List[Dict],
    config: Dict,
) -> Optional["BookGraph"]:
    """
    使用 Instructor 提取 BookGraph

    零报错 JSON 提取，直接返回 Pydantic 模型

    Args:
        messages: 消息列表
        config: 配置

    Returns:
        Optional[BookGraph]: 书籍知识图谱
    """
    from schemas.book_graph_schema import BookGraph

    llm_config = config.get("llm", {})

    wrapper = get_instructor_wrapper(
        provider=llm_config.get("provider", "openai"),
        model=llm_config.get("model", "gpt-4o-mini"),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("api_base"),
    )

    return await wrapper.aextract(
        BookGraph,
        messages,
        max_tokens=llm_config.get("max_tokens", 8192),
    )


async def extract_chunk_analysis_with_instructor(
    messages: List[Dict],
    config: Dict,
) -> Optional[BaseModel]:
    """
    使用 Instructor 提取 Chunk 分析结果

    Args:
        messages: 消息列表
        config: 配置

    Returns:
        Optional[BaseModel]: Chunk 分析结果
    """
    from schemas.book_graph_schema import CHUNK_ANALYSIS_JSON_SCHEMA
    from pydantic import BaseModel, Field
    from typing import List, Dict, Any

    # 定义 Chunk 分析模型
    class ChunkAnalysisResult(BaseModel):
        """Chunk 分析结果"""
        chapter_summaries: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="章节摘要列表"
        )
        core_concepts: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="核心概念列表"
        )
        key_insights: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="关键洞见列表"
        )
        key_cases: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="关键案例列表"
        )
        key_quotes: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="金句列表"
        )

    llm_config = config.get("llm", {})

    wrapper = get_instructor_wrapper(
        provider=llm_config.get("provider", "openai"),
        model=llm_config.get("model", "gpt-4o-mini"),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("api_base"),
    )

    return await wrapper.aextract(
        ChunkAnalysisResult,
        messages,
        max_tokens=llm_config.get("max_tokens", 8192),
    )


# ═══════════════════════════════════════════════════════════
# 使用示例
# ═══════════════════════════════════════════════════════════

async def example_usage():
    """使用示例"""

    from pydantic import BaseModel, Field
    from typing import List

    # 定义结构化输出模型
    class BookSummary(BaseModel):
        """书籍摘要"""
        title: str = Field(description="书名")
        author: str = Field(description="作者")
        main_themes: List[str] = Field(description="主要主题")
        key_concepts: List[str] = Field(description="核心概念")

    # 初始化 Instructor 封装器
    wrapper = get_instructor_wrapper(
        provider="openai",
        model="gpt-4o-mini",
    )

    # 定义消息
    messages = [
        {"role": "system", "content": "你是一位专业的书籍分析专家。"},
        {"role": "user", "content": "请分析《君主论》这本书的核心内容。"},
    ]

    # 提取结构化数据
    result = await wrapper.aextract(BookSummary, messages)

    if result:
        print(f"书名: {result.title}")
        print(f"作者: {result.author}")
        print(f"主要主题: {result.main_themes}")
        print(f"核心概念: {result.key_concepts}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
