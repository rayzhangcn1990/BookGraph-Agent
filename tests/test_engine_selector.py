#!/usr/bin/env python3
"""
引擎选择器 TDD 测试

测试覆盖：
- 正常场景：各类书籍的引擎选择
- 边界场景：极长/极短内容
- 边缘场景：未知学科、零基底
- 错误场景：无效输入
"""

import pytest
from core.engine_selector import (
    ExtractionEngine,
    TaskProfile,
    EngineRecommendation,
    EngineSelector,
    auto_select_engine
)


class TestExtractionEngine:
    """测试引擎枚举"""

    def test_engine_enum_values(self):
        """验证引擎枚举值"""
        assert ExtractionEngine.GRAPH_RAG.value == "GraphRAG"
        assert ExtractionEngine.LIGHT_RAG.value == "LightRAG"
        assert ExtractionEngine.HYPER_RAG.value == "Hyper-RAG"
        assert ExtractionEngine.KG_GEN.value == "KG-Gen"

    def test_engine_count(self):
        """验证引擎数量"""
        assert len(ExtractionEngine) == 7


class TestTaskProfile:
    """测试任务画像"""

    def test_profile_creation(self):
        """验证任务画像创建"""
        profile = TaskProfile(
            content_length=50000,
            discipline="政治学",
            kb_concepts_count=100,
            extraction_type="graph",
            has_complex_relations=True
        )
        assert profile.content_length == 50000
        assert profile.discipline == "政治学"
        assert profile.kb_concepts_count == 100

    def test_profile_defaults(self):
        """验证字段必填"""
        # TaskProfile 所有字段都是必填的（没有默认值）
        profile = TaskProfile(
            content_length=10000,
            discipline="经济学",
            kb_concepts_count=0,
            extraction_type="graph",
            has_complex_relations=False
        )
        assert profile.extraction_type == "graph"
        assert profile.has_complex_relations == False


class TestEngineSelector:
    """测试引擎选择器"""

    def test_select_for_large_politics_book(self):
        """测试大型政治学书籍"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=267000,  # 如《世界秩序》
            discipline="政治学",
            kb_concepts_count=100,
            extraction_type="graph",
            has_complex_relations=True
        )
        rec = selector.select_engine(profile)

        # 验证
        assert rec.primary_engine == ExtractionEngine.GRAPH_RAG
        assert rec.estimated_quality == "excellent"
        assert "政治学" in rec.reason or "267000" in rec.reason

    def test_select_for_medium_economics_book(self):
        """测试中等经济学书籍"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=25000,
            discipline="经济学",
            kb_concepts_count=30,
            extraction_type="graph",
            has_complex_relations=False
        )
        rec = selector.select_engine(profile)

        # 验证
        assert rec.primary_engine == ExtractionEngine.LIGHT_RAG
        assert rec.estimated_speed == "fast"

    def test_select_for_philosophy_with_reasoning(self):
        """测试哲学书籍（需要推理）"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=80000,
            discipline="哲学",
            kb_concepts_count=50,
            extraction_type="graph",
            has_complex_relations=True
        )
        rec = selector.select_engine(profile)

        # 哲学倾向 Cog-RAG 或 Hyper-RAG
        assert rec.estimated_quality == "excellent"

    def test_select_for_hypergraph_extraction(self):
        """测试超图抽取类型"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=50000,
            discipline="科学",
            kb_concepts_count=20,
            extraction_type="hypergraph",
            has_complex_relations=False
        )
        rec = selector.select_engine(profile)

        # 应选择 HypergraphRAG
        assert rec.primary_engine == ExtractionEngine.HYPERGRAPH_RAG

    def test_select_for_unknown_discipline(self):
        """测试未知学科"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=15000,
            discipline="未知学科",
            kb_concepts_count=0,
            extraction_type="graph",
            has_complex_relations=False
        )
        rec = selector.select_engine(profile)

        # 未知学科应返回通用引擎
        assert rec.primary_engine in [
            ExtractionEngine.KG_GEN,
            ExtractionEngine.LIGHT_RAG,
            ExtractionEngine.ITEXT2KG
        ]

    def test_select_for_zero_kb(self):
        """测试零知识基底"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=20000,
            discipline="政治学",
            kb_concepts_count=0,
            extraction_type="graph",
            has_complex_relations=False
        )
        rec = selector.select_engine(profile)

        # 零基底不影响引擎选择，但应正常返回
        assert rec.primary_engine is not None
        assert rec.reason != ""

    def test_select_for_extremely_short_content(self):
        """测试极短内容"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=1000,  # 仅1000字符
            discipline="经济学",
            kb_concepts_count=0,
            extraction_type="graph",
            has_complex_relations=False
        )
        rec = selector.select_engine(profile)

        # 极短内容应选择轻量引擎
        assert rec.primary_engine in [
            ExtractionEngine.LIGHT_RAG,
            ExtractionEngine.ITEXT2KG,
            ExtractionEngine.KG_GEN
        ]

    def test_select_for_extremely_long_content(self):
        """测试极长内容"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=1000000,  # 1百万字符
            discipline="历史学",
            kb_concepts_count=200,
            extraction_type="graph",
            has_complex_relations=True
        )
        rec = selector.select_engine(profile)

        # 极长内容应选择 GraphRAG
        assert rec.primary_engine == ExtractionEngine.GRAPH_RAG

    def test_fallback_engine_selection(self):
        """测试备选引擎"""
        selector = EngineSelector()
        profile = TaskProfile(
            content_length=50000,
            discipline="政治学",
            kb_concepts_count=100,
            extraction_type="graph",
            has_complex_relations=True
        )
        rec = selector.select_engine(profile)

        # 应有备选引擎（除非只有一个候选）
        if rec.fallback_engine:
            assert rec.fallback_engine != rec.primary_engine


class TestAutoSelectEngine:
    """测试便捷函数"""

    def test_auto_select_basic(self):
        """测试基本自动选择"""
        rec = auto_select_engine(
            content_length=50000,
            discipline="政治学",
            kb_concepts_count=100
        )

        assert rec.primary_engine is not None
        assert rec.reason != ""
        assert rec.estimated_speed in ["fast", "medium", "slow"]
        assert rec.estimated_quality in ["basic", "good", "excellent"]

    def test_auto_select_with_all_params(self):
        """测试完整参数"""
        rec = auto_select_engine(
            content_length=30000,
            discipline="社会学",
            kb_concepts_count=50,
            extraction_type="graph",
            has_complex_relations=True
        )

        assert rec.primary_engine == ExtractionEngine.HYPER_RAG

    def test_auto_select_returns_recommendation(self):
        """验证返回类型"""
        rec = auto_select_engine(
            content_length=10000,
            discipline="经济学",
            kb_concepts_count=0
        )

        assert isinstance(rec, EngineRecommendation)
        assert isinstance(rec.primary_engine, ExtractionEngine)


class TestEngineProfiles:
    """测试引擎特性矩阵"""

    def test_all_engines_have_profiles(self):
        """验证所有引擎都有特性定义"""
        selector = EngineSelector()

        for engine in ExtractionEngine:
            assert engine in selector.ENGINE_PROFILES
            profile = selector.ENGINE_PROFILES[engine]
            assert "min_length" in profile
            assert "max_length" in profile
            assert "quality" in profile
            assert "speed" in profile

    def test_engine_profile_quality_values(self):
        """验证质量值有效"""
        selector = EngineSelector()
        valid_qualities = ["basic", "good", "excellent"]

        for engine, profile in selector.ENGINE_PROFILES.items():
            assert profile["quality"] in valid_qualities

    def test_engine_profile_speed_values(self):
        """验证速度值有效"""
        selector = EngineSelector()
        valid_speeds = ["fast", "medium", "slow"]

        for engine, profile in selector.ENGINE_PROFILES.items():
            assert profile["speed"] in valid_speeds


class TestEdgeCases:
    """边缘场景测试"""

    def test_empty_discipline(self):
        """测试空学科"""
        rec = auto_select_engine(
            content_length=10000,
            discipline="",
            kb_concepts_count=0
        )
        # 应正常返回
        assert rec.primary_engine is not None

    def test_negative_concepts_count(self):
        """测试负数概念数（不应出现但需容错）"""
        # 这应该被处理或报错
        try:
            rec = auto_select_engine(
                content_length=10000,
                discipline="政治学",
                kb_concepts_count=-10
            )
            # 如果能运行，应返回有效结果
            assert rec.primary_engine is not None
        except ValueError:
            # 或者抛出错误也是合理的
            pass

    def test_very_small_content_length(self):
        """测试极小内容长度"""
        rec = auto_select_engine(
            content_length=0,
            discipline="经济学",
            kb_concepts_count=0
        )
        # 应返回默认引擎
        assert rec.primary_engine is not None


# ═══════════════════════════════════════════════════════════════════════
# 运行测试命令:
#   pytest tests/test_engine_selector.py -v
#   pytest tests/test_engine_selector.py --cov=core.engine_selector --cov-report=term
# ═══════════════════════════════════════════════════════════════════════