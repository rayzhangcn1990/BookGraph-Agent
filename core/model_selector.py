"""
模型自动选择器
- 自动检测可用模型
- 根据文本处理能力评分排序
- 自动切换到最优可用模型
"""

import httpx
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("BookGraph-Agent")

@dataclass
class ModelInfo:
    id: str
    owned_by: str
    text_capability_score: float  # 文本处理能力评分
    reasoning_score: float  # 推理能力评分
    context_window: int  # 上下文窗口大小（估计）

# 模型能力评分表（基于公开信息和测试）
MODEL_CAPABILITY_SCORES = {
    # Claude系列 - 文本理解和推理最强
    "claude-opus-4.7": {"text": 95, "reasoning": 98, "context": 200000},
    "claude-opus-4-7": {"text": 95, "reasoning": 98, "context": 200000},
    "claude-sonnet-4.6": {"text": 90, "reasoning": 92, "context": 200000},
    "claude-sonnet-4-6": {"text": 90, "reasoning": 92, "context": 200000},
    "claude-haiku-4.5": {"text": 80, "reasoning": 75, "context": 200000},
    "claude-haiku-4-5-20251001": {"text": 80, "reasoning": 75, "context": 200000},

    # DeepSeek系列 - 强推理
    "deepseek-r1": {"text": 85, "reasoning": 95, "context": 128000},
    "deepseek-v3": {"text": 85, "reasoning": 88, "context": 128000},

    # Qwen系列 - 国产强模型
    "qwen3-235b-a22b": {"text": 88, "reasoning": 85, "context": 128000},
    "qwen3-32b": {"text": 75, "reasoning": 70, "context": 128000},
    "qwen-plus": {"text": 70, "reasoning": 65, "context": 128000},
    "qwen-turbo": {"text": 60, "reasoning": 55, "context": 128000},

    # Gemini系列
    "gemini-2.5-pro": {"text": 88, "reasoning": 90, "context": 1000000},
    "gemini-2.5-flash": {"text": 75, "reasoning": 70, "context": 1000000},
    "gemini-3.1-pro-preview": {"text": 85, "reasoning": 85, "context": 1000000},

    # Llama系列
    "Meta-Llama-3.1-405B-Instruct": {"text": 82, "reasoning": 80, "context": 128000},
    "meta/llama-3.1-405b-instruct": {"text": 82, "reasoning": 80, "context": 128000},
    "meta/llama-3.3-70b-instruct": {"text": 70, "reasoning": 65, "context": 128000},

    # GPT系列
    "gpt-5.4": {"text": 85, "reasoning": 88, "context": 128000},
    "gpt-5.2-codex": {"text": 70, "reasoning": 60, "context": 128000},  # 代码模型
    "gpt-4.1": {"text": 80, "reasoning": 82, "context": 128000},
    "gpt-4o": {"text": 78, "reasoning": 75, "context": 128000},

    # 其他
    "minimax-m2.5": {"text": 75, "reasoning": 70, "context": 128000},
    "moonshotai/kimi-k2-instruct": {"text": 78, "reasoning": 75, "context": 128000},
}


class ModelSelector:
    """模型自动选择器"""

    def __init__(self, api_base: str, api_key: str = "unused"):
        self.api_base = api_base
        self.api_key = api_key
        self.available_models: List[ModelInfo] = []
        self.current_model: Optional[str] = None
        self.failed_models: set = set()

    async def fetch_available_models(self) -> List[ModelInfo]:
        """获取可用模型列表"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.api_base}/v1/models",
                    headers={"x-api-key": self.api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("data", []):
                        model_id = model.get("id", "")
                        # 获取评分，没有评分的模型使用默认值
                        scores = MODEL_CAPABILITY_SCORES.get(model_id, {
                            "text": 50, "reasoning": 50, "context": 32000
                        })
                        models.append(ModelInfo(
                            id=model_id,
                            owned_by=model.get("owned_by", ""),
                            text_capability_score=scores["text"],
                            reasoning_score=scores["reasoning"],
                            context_window=scores["context"]
                        ))
                    self.available_models = models
                    return models
                else:
                    logger.warning(f"获取模型列表失败: {response.status_code}")
                    return []
        except Exception as e:
            logger.error(f"获取模型列表异常: {e}")
            return []

    def get_best_model_for_text_processing(self, task_type: str = "extraction") -> Optional[str]:
        """根据任务类型选择最佳模型

        task_type:
        - extraction: 知识抽取（需要强推理和文本理解）
        - synthesis: 综合（需要强推理和整合能力）
        - simple: 简单任务（可用较快模型）
        """
        if not self.available_models:
            return None

        # 过滤掉已失败的模型
        candidates = [m for m in self.available_models if m.id not in self.failed_models]

        if task_type == "extraction":
            # 知识抽取：优先推理能力
            candidates.sort(key=lambda m: (m.reasoning_score, m.text_capability_score), reverse=True)
        elif task_type == "synthesis":
            # 综合：推理和文本同等重要
            candidates.sort(key=lambda m: (m.reasoning_score + m.text_capability_score) / 2, reverse=True)
        else:
            # 简单任务：优先速度（文本能力够用即可）
            candidates.sort(key=lambda m: m.text_capability_score, reverse=True)

        if candidates:
            best = candidates[0]
            logger.info(f"🧠 选择模型: {best.id} (推理:{best.reasoning_score}, 文本:{best.text_capability_score})")
            return best.id
        return None

    def mark_model_failed(self, model_id: str):
        """标记模型失败"""
        self.failed_models.add(model_id)
        logger.warning(f"⚠️ 模型失败标记: {model_id}")

    def get_fallback_model(self) -> Optional[str]:
        """获取备用模型"""
        return self.get_best_model_for_text_processing()

    def clear_failed_models(self):
        """清除失败标记（用于重试）"""
        self.failed_models.clear()


async def test_model_availability(api_base: str, model: str, api_key: str = "unused") -> bool:
    """测试模型是否可用"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 发送简单测试请求
            response = await client.post(
                f"{api_base}/v1/chat/completions",
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 10
                }
            )
            return response.status_code == 200
    except Exception as e:
        logger.warning(f"模型 {model} 测试失败: {e}")
        return False


async def auto_select_model(config: dict) -> str:
    """根据配置自动选择最佳可用模型"""
    api_base = config.get("api_base", "http://localhost:18765")
    api_key = config.get("api_key", "unused")

    selector = ModelSelector(api_base, api_key)
    models = await selector.fetch_available_models()

    if not models:
        logger.warning("无法获取模型列表，使用默认模型")
        return config.get("model", "claude-sonnet-4-6")

    # 测试候选模型可用性
    best_model = selector.get_best_model_for_text_processing("extraction")

    if best_model:
        # 验证可用性
        if await test_model_availability(api_base, best_model, api_key):
            logger.info(f"✅ 自动选择模型: {best_model}")
            return best_model
        else:
            selector.mark_model_failed(best_model)
            # 尝试备用模型
            fallback = selector.get_fallback_model()
            if fallback and await test_model_availability(api_base, fallback, api_key):
                logger.info(f"✅ 使用备用模型: {fallback}")
                return fallback

    # 所有测试失败，返回评分最高的模型（可能是网络问题）
    best = selector.get_best_model_for_text_processing("extraction")
    if best:
        logger.warning(f"⚠️ 模型测试失败，使用评分最高模型: {best}")
        return best

    return config.get("model", "claude-sonnet-4-6")