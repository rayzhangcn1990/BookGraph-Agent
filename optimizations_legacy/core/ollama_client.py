"""
Ollama 本地模型客户端
针对 Qwen2.5:7B 优化，通过 SSH 隧道连接 NAS
"""
import requests
import time
from typing import Dict, List, Optional
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class OllamaClient:
    """Ollama 本地模型客户端"""

    def __init__(self,
                 base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:7b",
                 timeout: int = 300):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self._verify_connection()
        logger.info(f"Ollama 客户端: {base_url} | 模型: {model}")

    def _verify_connection(self):
        """验证 Ollama 服务连接"""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m['name'] for m in resp.json().get('models', [])]
            logger.info(f"可用模型: {models}")
            if self.model not in models:
                logger.warning(f"模型 {self.model} 未在列表中，尝试使用")
        except Exception as e:
            logger.error(f"无法连接 Ollama: {e}")
            raise ConnectionError(f"Ollama 不可用: {self.base_url}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate(self,
                 prompt: str,
                 system_prompt: Optional[str] = None,
                 temperature: float = 0.2,
                 max_tokens: int = 4096,
                 **kwargs) -> str:
        """生成文本（同步）"""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload["options"].update(kwargs)

        try:
            t0 = time.time()
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            result = resp.json()
            text = result.get('response', '')
            elapsed = time.time() - t0
            tokens = result.get('eval_count', 0)
            logger.info(f"生成: {elapsed:.1f}s | {tokens} tokens | {tokens/max(elapsed,0.1):.1f} tok/s")
            return text
        except requests.exceptions.Timeout:
            logger.error("请求超时")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            raise

    def chat(self,
             messages: List[Dict[str, str]],
             temperature: float = 0.2,
             **kwargs) -> str:
        """对话模式"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }
        payload["options"].update(kwargs)

        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get('message', {}).get('content', '')
        except Exception as e:
            logger.error(f"对话请求失败: {e}")
            raise

    def test_generation(self) -> bool:
        """测试生成功能"""
        try:
            result = self.generate("请用一句话介绍知识图谱。", max_tokens=100)
            logger.info(f"测试结果: {result[:80]}...")
            return len(result) > 0
        except Exception as e:
            logger.error(f"测试失败: {e}")
            return False


if __name__ == "__main__":
    client = OllamaClient()
    if client.test_generation():
        print("✅ Ollama 客户端工作正常")
    else:
        print("❌ Ollama 客户端测试失败")
