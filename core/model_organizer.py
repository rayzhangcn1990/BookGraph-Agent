"""
模型整理器
- 从所有 API 源获取可用模型
- 按性能排序
- 在任务执行前自动整理
"""

import httpx
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import yaml
import json

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ModelInfo:
    model_id: str
    source_name: str
    source_priority: int
    performance_score: int  # 1-100，越高越好
    is_free: bool
    provider: str  # openai, anthropic, google, meta, deepseek, etc.


class ModelOrganizer:
    """模型整理器"""

    # 高性能模型评分表
    PERFORMANCE_RANKING = {
        # Claude 系列（推理最强）
        "claude-opus": 100,
        "claude-sonnet": 95,
        "claude-haiku": 80,

        # GPT 系列
        "gpt-5.5": 98,
        "gpt-5.4": 95,
        "gpt-5": 92,
        "gpt-4o": 85,
        "gpt-4": 80,

        # Gemini 系列
        "gemini-3": 95,
        "gemini-2.5-pro": 90,
        "gemini-2.5-flash": 75,
        "gemini-2.0": 70,

        # DeepSeek 系列
        "deepseek-v4-pro": 88,
        "deepseek-v4": 85,
        "deepseek-v3": 80,
        "deepseek-r1": 92,

        # Qwen 系列
        "qwen3": 85,
        "qwen-": 75,

        # Llama 系列
        "llama-4": 82,
        "llama-3.3": 78,
        "llama-3.1": 75,

        # 其他
        "grok": 85,
        "minimax": 80,
    }

    # 推荐用于书籍解析的模型（需要强推理能力）
    RECOMMENDED_FOR_BOOK_PARSING = [
        "claude-opus-4.7",
        "claude-sonnet-4.6",
        "claude-sonnet-4-6",
        "deepseek-r1",
        "gemini-2.5-pro",
        "gpt-5.4",
        "deepseek-v4-pro",
        "gpt-4o",
    ]

    def __init__(self, config: Dict):
        """
        Args:
            config: llm配置部分
        """
        self.config = config
        self.organized_models: List[ModelInfo] = []
        self.best_models_per_source: Dict[str, List[ModelInfo]] = {}

    def organize_all_models(self) -> List[ModelInfo]:
        """
        从所有 API 源获取并整理模型

        Returns:
            List[ModelInfo]: 按性能排序的模型列表
        """
        api_sources = self.config.get("api_sources", [])
        all_models = []

        print("\n" + "=" * 60)
        print("🧠 整理所有可用模型")
        print("=" * 60)

        for source in api_sources:
            source_name = source.get("name", "unknown")
            api_base = source.get("api_base", "")
            api_key = source.get("api_key", "unused")
            priority = source.get("priority", 99)

            if not api_base:
                continue

            # 构建请求头
            headers = {
                "Authorization": f"Bearer {api_key}",
            }

            # OpenRouter 需要特殊头
            if "openrouter" in source_name.lower():
                headers["HTTP-Referer"] = "https://bookgraph.app"
                headers["X-Title"] = "BookGraph-Agent"

            try:
                test_url = api_base.rstrip("/") + "/models"
                response = httpx.get(test_url, headers=headers, timeout=15)

                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", [])

                    source_models = []
                    for m in models:
                        model_id = m.get("id", "unknown")

                        # 计算性能评分
                        score = self._calculate_score(model_id)
                        is_free = ":free" in model_id or "free" in model_id.lower()
                        provider = self._detect_provider(model_id)

                        model_info = ModelInfo(
                            model_id=model_id,
                            source_name=source_name,
                            source_priority=priority,
                            performance_score=score,
                            is_free=is_free,
                            provider=provider,
                        )

                        source_models.append(model_info)
                        all_models.append(model_info)

                    # 按评分排序当前源的模型
                    source_models.sort(key=lambda x: x.performance_score, reverse=True)
                    self.best_models_per_source[source_name] = source_models

                    print(f"\n✅ {source_name}: {len(source_models)} 个模型")
                    top3 = source_models[:3]
                    for m in top3:
                        print(f"   📋 {m.model_id} (评分: {m.performance_score})")

                else:
                    print(f"❌ {source_name}: HTTP {response.status_code}")

            except Exception as e:
                print(f"❌ {source_name}: {str(e)[:40]}")

        # 全局排序：按评分 + 源优先级
        all_models.sort(
            key=lambda x: (x.performance_score, -x.source_priority),
            reverse=True
        )

        self.organized_models = all_models

        print("\n" + "=" * 60)
        print("📊 全局推荐模型（用于书籍解析）")
        print("=" * 60)

        # 输出推荐模型
        recommended = self._get_recommended_models(all_models)
        for i, m in enumerate(recommended[:10], 1):
            print(f"{i}. {m.model_id} @ {m.source_name} (评分: {m.performance_score})")

        print("=" * 60)

        return all_models

    def _calculate_score(self, model_id: str) -> int:
        """计算模型性能评分"""
        model_lower = model_id.lower()

        for pattern, score in self.PERFORMANCE_RANKING.items():
            if pattern.lower() in model_lower:
                return score

        # 默认评分
        return 50

    def _detect_provider(self, model_id: str) -> str:
        """检测模型提供商"""
        model_lower = model_id.lower()

        if "claude" in model_lower:
            return "anthropic"
        if "gpt" in model_lower:
            return "openai"
        if "gemini" in model_lower:
            return "google"
        if "deepseek" in model_lower:
            return "deepseek"
        if "qwen" in model_lower:
            return "alibaba"
        if "llama" in model_lower:
            return "meta"
        if "grok" in model_lower:
            return "xai"
        if "minimax" in model_lower:
            return "minimax"

        return "unknown"

    def _get_recommended_models(self, models: List[ModelInfo]) -> List[ModelInfo]:
        """获取推荐用于书籍解析的模型"""
        recommended = []

        for pattern in self.RECOMMENDED_FOR_BOOK_PARSING:
            pattern_lower = pattern.lower()
            matching = [m for m in models if pattern_lower in m.model_id.lower()]
            if matching:
                # 选择评分最高的
                best = max(matching, key=lambda x: x.performance_score)
                recommended.append(best)

        return recommended

    def get_best_model_for_source(self, source_name: str) -> Optional[ModelInfo]:
        """获取指定源的最佳模型"""
        models = self.best_models_per_source.get(source_name, [])
        if models:
            return models[0]
        return None

    def save_model_list(self, output_path: str = "organized_models.json"):
        """保存整理后的模型列表"""
        data = {
            "total_models": len(self.organized_models),
            "sources": {
                name: [{"id": m.model_id, "score": m.performance_score} for m in models]
                for name, models in self.best_models_per_source.items()
            },
            "recommended": [
                {"id": m.model_id, "source": m.source_name, "score": m.performance_score}
                for m in self._get_recommended_models(self.organized_models)[:10]
            ],
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ 模型列表已保存到 {output_path}")

    def get_model_rotation_list(self) -> List[str]:
        """获取模型轮换列表（用于 LLMClient）"""
        # 按评分排序，排除免费模型（除非没有其他选择）
        paid_models = [m for m in self.organized_models if not m.is_free]
        free_models = [m for m in self.organized_models if m.is_free]

        # 付费模型优先
        rotation_list = [m.model_id for m in paid_models]

        # 添加免费模型作为后备
        rotation_list.extend([m.model_id for m in free_models])

        return rotation_list


def organize_models_before_task(config_path: str = "config.yaml") -> List[str]:
    """
    任务执行前整理模型

    Args:
        config_path: 配置文件路径

    Returns:
        List[str]: 模型轮换列表
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    llm_config = config.get("llm", {})

    organizer = ModelOrganizer(llm_config)
    organizer.organize_all_models()

    # 保存模型列表
    organizer.save_model_list()

    # 返回轮换列表
    return organizer.get_model_rotation_list()


if __name__ == "__main__":
    # 测试
    rotation_list = organize_models_before_task()
    print(f"\n模型轮换列表: {len(rotation_list)} 个模型")
    print(f"前5个: {rotation_list[:5]}")