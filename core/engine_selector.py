#!/usr/bin/env python3
"""
Hyper-Extract 引擎自动化选择器

根据任务特征自动匹配最优引擎：
- 内容长度
- 学科类型
- 已有知识基底规模
- 抽取目标类型

引擎列表（基于 Hyper-Extract 文档）：
- GraphRAG：适合大规模文档，图谱检索增强
- LightRAG：适合中等规模，轻量级快速抽取
- Hyper-RAG：适合复杂关系抽取
- HypergraphRAG：适合超图结构（多实体关系）
- Cog-RAG：适合认知推理型抽取
- KG-Gen：适合知识图谱生成
- iText2KG：适合文本到图谱转换
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ExtractionEngine(Enum):
    """抽取引擎类型"""
    GRAPH_RAG = "GraphRAG"
    LIGHT_RAG = "LightRAG"
    HYPER_RAG = "Hyper-RAG"
    HYPERGRAPH_RAG = "HypergraphRAG"
    COG_RAG = "Cog-RAG"
    KG_GEN = "KG-Gen"
    ITEXT2KG = "iText2KG"


@dataclass
class TaskProfile:
    """任务画像"""
    content_length: int  # 字符数
    discipline: str  # 学科
    kb_concepts_count: int  # 已有概念数
    extraction_type: str  # 抽取类型：graph/hypergraph/spatiotemporal
    has_complex_relations: bool  # 是否有复杂关系


@dataclass
class EngineRecommendation:
    """引擎推荐"""
    primary_engine: ExtractionEngine
    fallback_engine: Optional[ExtractionEngine]
    reason: str
    estimated_speed: str  # fast/medium/slow
    estimated_quality: str  # basic/good/excellent


class EngineSelector:
    """引擎选择器"""

    # 引擎特性矩阵
    ENGINE_PROFILES = {
        ExtractionEngine.GRAPH_RAG: {
            "min_length": 50000,
            "max_length": 500000,
            "disciplines": ["政治学", "历史学", "哲学"],
            "quality": "excellent",
            "speed": "slow",
            "kb_dependency": "high",
        },
        ExtractionEngine.LIGHT_RAG: {
            "min_length": 5000,
            "max_length": 50000,
            "disciplines": ["经济学", "管理学", "心理学"],
            "quality": "good",
            "speed": "fast",
            "kb_dependency": "medium",
        },
        ExtractionEngine.HYPER_RAG: {
            "min_length": 30000,
            "max_length": 200000,
            "disciplines": ["社会学", "政治学"],
            "quality": "excellent",
            "speed": "medium",
            "kb_dependency": "high",
            "complex_relations": True,
        },
        ExtractionEngine.HYPERGRAPH_RAG: {
            "min_length": 10000,
            "max_length": 100000,
            "disciplines": ["科学", "技术"],
            "quality": "excellent",
            "speed": "medium",
            "extraction_type": "hypergraph",
        },
        ExtractionEngine.COG_RAG: {
            "min_length": 20000,
            "max_length": 100000,
            "disciplines": ["哲学", "心理学"],
            "quality": "excellent",
            "speed": "slow",
            "reasoning_intensive": True,
        },
        ExtractionEngine.KG_GEN: {
            "min_length": 10000,
            "max_length": 50000,
            "disciplines": ["all"],
            "quality": "good",
            "speed": "fast",
            "kb_dependency": "low",
        },
        ExtractionEngine.ITEXT2KG: {
            "min_length": 5000,
            "max_length": 30000,
            "disciplines": ["all"],
            "quality": "basic",
            "speed": "fast",
            "kb_dependency": "low",
        },
    }

    def select_engine(self, profile: TaskProfile) -> EngineRecommendation:
        """
        自动选择最优引擎

        Args:
            profile: 任务画像

        Returns:
            EngineRecommendation: 引擎推荐
        """
        candidates = []

        for engine, features in self.ENGINE_PROFILES.items():
            score = self._calculate_score(profile, engine, features)
            if score > 0:
                candidates.append((engine, score, features))

        if not candidates:
            # 默认推荐
            return EngineRecommendation(
                primary_engine=ExtractionEngine.LIGHT_RAG,
                fallback_engine=ExtractionEngine.KG_GEN,
                reason="默认引擎：适合中等规模通用任务",
                estimated_speed="fast",
                estimated_quality="good"
            )

        # 按得分排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_engine, best_score, best_features = candidates[0]

        # 选择备选引擎
        fallback = candidates[1][0] if len(candidates) > 1 else None

        reason = self._generate_reason(profile, best_engine, best_features)

        logger.info(f"🎯 引擎选择: {best_engine.value} (得分: {best_score})")

        return EngineRecommendation(
            primary_engine=best_engine,
            fallback_engine=fallback,
            reason=reason,
            estimated_speed=best_features["speed"],
            estimated_quality=best_features["quality"]
        )

    def _calculate_score(self, profile: TaskProfile, engine: ExtractionEngine, features: Dict) -> float:
        """计算引擎匹配得分"""
        score = 0.0

        # 1. 内容长度匹配
        if profile.content_length >= features["min_length"] and profile.content_length <= features["max_length"]:
            score += 30  # 长度匹配加30分
        elif profile.content_length < features["min_length"]:
            score -= 10  # 过短扣分
        elif profile.content_length > features["max_length"]:
            score -= 5  # 过长轻微扣分

        # 2. 学科匹配
        if features["disciplines"] == ["all"]:
            score += 20  # 通用引擎加20分
        elif profile.discipline in features["disciplines"]:
            score += 40  # 学科匹配加40分

        # 3. 知识基底依赖
        kb_dependency = features.get("kb_dependency", "low")
        if kb_dependency == "high" and profile.kb_concepts_count > 50:
            score += 30  # 有丰富基底且引擎需要
        elif kb_dependency == "low":
            score += 10  # 低依赖更灵活

        # 4. 抽取类型匹配
        extraction_type = features.get("extraction_type")
        if extraction_type and extraction_type == profile.extraction_type:
            score += 50  # 类型精确匹配

        # 5. 复杂关系
        if features.get("complex_relations") and profile.has_complex_relations:
            score += 30

        return score

    def _generate_reason(self, profile: TaskProfile, engine: ExtractionEngine, features: Dict) -> str:
        """生成选择原因说明"""
        reasons = []

        # 长度匹配
        if profile.content_length >= features["min_length"] and profile.content_length <= features["max_length"]:
            reasons.append(f"内容长度{profile.content_length}字符在引擎最佳范围({features['min_length']}-{features['max_length']})")

        # 学科匹配
        if profile.discipline in features["disciplines"] or features["disciplines"] == ["all"]:
            reasons.append(f"学科'{profile.discipline}'适配")

        # 知识基底
        if features.get("kb_dependency") == "high":
            reasons.append(f"知识基底{profile.kb_concepts_count}概念可增强抽取效果")

        return "; ".join(reasons) if reasons else "综合评分最优"


# 便捷函数
def auto_select_engine(
    content_length: int,
    discipline: str,
    kb_concepts_count: int = 0,
    extraction_type: str = "graph",
    has_complex_relations: bool = False
) -> EngineRecommendation:
    """便捷函数：自动选择引擎"""
    selector = EngineSelector()
    profile = TaskProfile(
        content_length=content_length,
        discipline=discipline,
        kb_concepts_count=kb_concepts_count,
        extraction_type=extraction_type,
        has_complex_relations=has_complex_relations
    )
    return selector.select_engine(profile)