"""
Claude API 客户端（通过 DashScope 代理）
替代 Ollama 用于 BookGraph-Agent
"""
import time
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class ClaudeClient:
    """Claude API 客户端（Anthropic SDK 兼容 DashScope 代理）"""

    def __init__(self,
                 api_key: str = None,
                 base_url: str = None,
                 model: str = "glm-5",
                 timeout: int = 300):
        import anthropic

        # 优先级：参数 > 环境变量 > Claude Code settings.json
        import os
        self.api_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "glm-5")

        # 从 Claude Code settings.json 兜底读取
        if not self.api_key or not self.base_url:
            self._load_claude_settings()
            self.api_key = self.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
            self.base_url = self.base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
            self.model = self.model or os.environ.get("ANTHROPIC_MODEL", "glm-5")

        self.timeout = timeout

        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        logger.info(f"Claude 客户端: {self.base_url} | 模型: {self.model}")

    @staticmethod
    def _load_claude_settings() -> dict:
        """从 Claude Code settings.json 读取配置"""
        import os
        import json
        settings_path = Path.home() / ".claude" / "settings.json"
        if not settings_path.exists():
            return {}
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            env = settings.get("env", {})
            for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
                if key in env and not os.environ.get(key):
                    os.environ[key] = env[key]
            return env
        except Exception:
            return {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate(self,
                 prompt: str,
                 system_prompt: Optional[str] = None,
                 temperature: float = 0.2,
                 max_tokens: int = 4096,
                 **kwargs) -> str:
        """生成文本（同步）"""
        messages = [{"role": "user", "content": prompt}]
        params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            params["system"] = system_prompt

        try:
            t0 = time.time()
            response = self.client.messages.create(**params)
            elapsed = time.time() - t0
            # 提取文本内容（跳过 ThinkingBlock 等非文本块）
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            tokens_in = response.usage.input_tokens if response.usage else 0
            tokens_out = response.usage.output_tokens if response.usage else 0
            logger.info(
                f"生成: {elapsed:.1f}s | 入{tokens_in} 出{tokens_out} tokens"
            )
            return text
        except Exception as e:
            logger.error(f"请求失败: {e}")
            raise

    def chat(self,
             messages: List[Dict[str, str]],
             temperature: float = 0.2,
             max_tokens: int = 4096,
             **kwargs) -> str:
        """对话模式"""
        params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        try:
            response = self.client.messages.create(**params)
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            return text
        except Exception as e:
            logger.error(f"对话请求失败: {e}")
            raise

    def test_generation(self) -> bool:
        """测试生成功能"""
        try:
            result = self.generate("用一句话介绍知识图谱。", max_tokens=100)
            logger.info(f"测试结果: {result[:80]}...")
            return len(result) > 0
        except Exception as e:
            logger.error(f"测试失败: {e}")
            return False


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    client = ClaudeClient()
    if client.test_generation():
        print("✅ Claude 客户端工作正常")
    else:
        print("❌ Claude 客户端测试失败")
