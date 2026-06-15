#!/usr/bin/env python3
"""
引擎选择器模块

根据书籍特征自动选择最合适的知识抽取引擎。
支持 GraphRAG、LightRAG、Hyper-RAG 等多种引擎。
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ExtractionEngine(Enum):
    """知识抽取引擎枚举"""
    GRAPH_RAG = "GraphRAG"
    LIGHT_RAG = "LightRAG"
    HYPER_RAG = "Hyper-RAG"
    KG_GEN = "KG-Gen"
    HYPERGRAPH_RAG = "HypergraphRAG"
    ITEXT2KG = "iText2KG"
    COG_RAG = "Cog-RAG"


@dataclass
class TaskProfile:
    """任务画像"""
    content_length: int
    discipline: str
    kb_concepts_count: int
    extraction_type: str
    has_complex_relations: bool


@dataclass
class EngineRecommendation:
    """引擎推荐结果"""
    primary_engine: ExtractionEngine
    fallback_engine: Optional[ExtractionEngine]
    estimated_quality: str  # "basic", "good", "excellent"
    estimated_speed: str    # "fast", "medium", "slow"
    reason: str


class EngineSelector:
    """引擎选择器"""

    # 引擎特性矩阵
    ENGINE_PROFILES = {
        ExtractionEngine.GRAPH_RAG: {
            "min_length": 100000,
            "max_length": float('inf'),
            "quality": "excellent",
            "speed": "slow",
            "best_for": ["政治学", "历史学", "社会学"],
            "supports_hypergraph": False
        },
        ExtractionEngine.LIGHT_RAG: {
            "min_length": 10000,
            "max_length": 100000,
            "quality": "good",
            "speed": "fast",
            "best_for": ["经济学", "管理学", "心理学"],
            "supports_hypergraph": False
        },
        ExtractionEngine.HYPER_RAG: {
            "min_length": 20000,
            "max_length": 300000,
            "quality": "excellent",
            "speed": "medium",
            "best_for": ["哲学", "逻辑学", "科学", "社会学"],
            "supports_hypergraph": False
        },
        ExtractionEngine.KG_GEN: {
            "min_length": 0,
            "max_length": 50000,
            "quality": "basic",
            "speed": "fast",
            "best_for": [],  # 通用引擎
            "supports_hypergraph": False
        },
        ExtractionEngine.HYPERGRAPH_RAG: {
            "min_length": 20000,
            "max_length": 200000,
            "quality": "excellent",
            "speed": "medium",
            "best_for": ["科学", "复杂性研究"],
            "supports_hypergraph": True
        },
        ExtractionEngine.ITEXT2KG: {
            "min_length": 0,
            "max_length": 30000,
            "quality": "basic",
            "speed": "fast",
            "best_for": [],
            "supports_hypergraph": False
        },
        ExtractionEngine.COG_RAG: {
            "min_length": 30000,
            "max_length": 150000,
            "quality": "excellent",
            "speed": "medium",
            "best_for": ["哲学", "认知科学"],
            "supports_hypergraph": False
        }
    }

    def select_engine(self, profile: TaskProfile) -> EngineRecommendation:
        """
        根据任务画像选择最合适的引擎

        Args:
            profile: 任务画像

        Returns:
            EngineRecommendation: 引擎推荐结果
        """
        # 验证输入
        if profile.content_length < 0:
            raise ValueError(f"content_length 不能为负数: {profile.content_length}")

        if profile.kb_concepts_count < 0:
            raise ValueError(f"kb_concepts_count 不能为负数: {profile.kb_concepts_count}")

        # 特殊情况：超图抽取
        if profile.extraction_type == "hypergraph":
            return EngineRecommendation(
                primary_engine=ExtractionEngine.HYPERGRAPH_RAG,
                fallback_engine=ExtractionEngine.GRAPH_RAG,
                estimated_quality="excellent",
                estimated_speed="medium",
                reason=f"超图抽取类型自动选择 HypergraphRAG"
            )

        # 筛选候选引擎
        candidates = []

        for engine, engine_profile in self.ENGINE_PROFILES.items():
            # 跳过超图专用引擎
            if engine == ExtractionEngine.HYPERGRAPH_RAG:
                continue

            # 长度范围检查
            if not (engine_profile["min_length"] <= profile.content_length <= engine_profile["max_length"]):
                continue

            # 计算匹配分数
            score = 0

            # 学科匹配（最高优先级）
            if profile.discipline in engine_profile["best_for"]:
                score += 5  # 提高学科匹配权重

            # 复杂关系处理
            if profile.has_complex_relations and engine_profile["quality"] == "excellent":
                score += 2

            # 知识库概念数越多，越倾向高质量引擎
            if profile.kb_concepts_count > 50 and engine_profile["quality"] == "excellent":
                score += 2
            elif profile.kb_concepts_count > 20 and engine_profile["quality"] in ["good", "excellent"]:
                score += 1

            candidates.append((engine, score, engine_profile))

        # 如果没有候选，使用通用引擎
        if not candidates:
            return EngineRecommendation(
                primary_engine=ExtractionEngine.KG_GEN,
                fallback_engine=ExtractionEngine.LIGHT_RAG,
                estimated_quality="basic",
                estimated_speed="fast",
                reason=f"未找到匹配引擎，使用通用引擎 KG-Gen"
            )

        # 按分数排序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 选择最佳引擎
        primary_engine, primary_score, primary_profile = candidates[0]
        fallback_engine = candidates[1][0] if len(candidates) > 1 else None

        # 构建推荐原因
        reasons = []
        if profile.discipline in primary_profile["best_for"]:
            reasons.append(f"学科 '{profile.discipline}' 匹配")
        if profile.content_length > 100000:
            reasons.append(f"大型书籍 ({profile.content_length} 字符)")
        if profile.has_complex_relations:
            reasons.append("包含复杂关系")
        if profile.kb_concepts_count > 50:
            reasons.append(f"知识库概念丰富 ({profile.kb_concepts_count})")

        reason = "、".join(reasons) if reasons else f"内容长度 {profile.content_length} 适合该引擎"

        return EngineRecommendation(
            primary_engine=primary_engine,
            fallback_engine=fallback_engine,
            estimated_quality=primary_profile["quality"],
            estimated_speed=primary_profile["speed"],
            reason=reason
        )


def auto_select_engine(
    content_length: int,
    discipline: str,
    kb_concepts_count: int,
    extraction_type: str = "graph",
    has_complex_relations: bool = False
) -> EngineRecommendation:
    """
    自动选择引擎的便捷函数

    Args:
        content_length: 内容长度（字符数）
        discipline: 学科名称
        kb_concepts_count: 知识库概念数量
        extraction_type: 抽取类型（"graph" 或 "hypergraph"）
        has_complex_relations: 是否包含复杂关系

    Returns:
        EngineRecommendation: 引擎推荐结果
    """
    profile = TaskProfile(
        content_length=content_length,
        discipline=discipline,
        kb_concepts_count=kb_concepts_count,
        extraction_type=extraction_type,
        has_complex_relations=has_complex_relations
    )

    selector = EngineSelector()
    return selector.select_engine(profile)
