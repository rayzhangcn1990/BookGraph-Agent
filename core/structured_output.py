"""
结构化输出保证模块
使用 instructor 库或原生 Pydantic JSON schema 强制 LLM 返回有效 JSON。
"""

import json
import logging
from typing import TypeVar, Type, Optional, Any, Dict
from pydantic import BaseModel

logger = logging.getLogger("BookGraph-Agent")

T = TypeVar('T', bound=BaseModel)

# 尝试导入 instructor
try:
    import instructor
    from openai import OpenAI
    INSTRUCTOR_AVAILABLE = True
except ImportError:
    INSTRUCTOR_AVAILABLE = False


class StructuredOutputHandler:
    """处理结构化输出"""

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self._instructor_client = None
        if INSTRUCTOR_AVAILABLE:
            # 尝试从 llm_client 获取 openai 客户端
            if hasattr(llm_client, 'openai_client') and llm_client.openai_client:
                self._instructor_client = instructor.from_openai(llm_client.openai_client)
                logger.info("✅ Instructor 客户端初始化成功")
            else:
                logger.warning("⚠️ 无法初始化 instructor 客户端: 缺少 openai_client")
        else:
            logger.info("ℹ️ instructor 未安装，将使用 Pydantic JSON schema 方式")

    def extract_with_model(
        self,
        model: Type[T],
        messages: list,
        max_retries: int = 2,
        temperature: float = 0.2
    ) -> Optional[T]:
        """
        使用 instructor 或原生方式强制 LLM 输出符合 model 的 JSON。

        Args:
            model: Pydantic 模型类
            messages: 消息列表（openai 格式）
            max_retries: 最大重试次数
            temperature: 温度

        Returns:
            模型实例，失败返回 None
        """
        if self._instructor_client:
            try:
                response = self._instructor_client.chat.completions.create(
                    model=self.llm_client.model,
                    messages=messages,
                    response_model=model,
                    max_retries=max_retries,
                    temperature=temperature
                )
                return response
            except Exception as e:
                logger.warning(f"Instructor 调用失败: {e}，回退到原生方式")

        # 回退：使用原生 LLM + 手动 JSON 解析 + Pydantic 验证
        schema = model.model_json_schema()
        prompt_addendum = f"\n\n你必须输出严格的 JSON 对象，符合以下 JSON Schema:\n{json.dumps(schema, indent=2)}"

        # 修改最后一条消息，添加 schema 提示
        modified_messages = list(messages)
        if modified_messages and modified_messages[-1]['role'] == 'user':
            modified_messages[-1]['content'] += prompt_addendum
        else:
            modified_messages.append({'role': 'user', 'content': prompt_addendum})

        for attempt in range(max_retries):
            try:
                response = self.llm_client._call_llm(modified_messages, max_tokens=4096)
                if not response:
                    continue
                # 提取 JSON
                json_str = self._extract_json(response)
                if not json_str:
                    continue
                data = json.loads(json_str)
                obj = model.model_validate(data)
                return obj
            except Exception as e:
                logger.warning(f"结构化输出解析失败 (尝试 {attempt+1}/{max_retries}): {e}")
                continue
        return None

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """从 LLM 响应中提取 JSON 字符串"""
        import re
        # 尝试匹配 ```json ... ``` 或直接 { ... }
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if not match:
            match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            return match.group(1)
        return None
