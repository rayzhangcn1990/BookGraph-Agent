"""
test_graph_generator.py - GraphGenerator 测试

测试核心功能：
- BookGraph Markdown 生成
- DisciplineGraph Markdown 生成
- YAML Front Matter 格式
- Obsidian Callout 语法
"""

import pytest
from pathlib import Path
import sys
import re
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.graph_generator import GraphGenerator
from schemas.book_graph_schema import (
    BookGraph, BookMetadata, TimeBackground, DisciplineType,
    ChapterSummary, CoreConcept, KeyInsight, KeyCase, KeyQuote,
    CriticalAnalysis
)
from schemas.discipline_schema import (
    DisciplineGraph, DisciplineOverview, KnowledgeStructure,
    DevelopmentStage, CoreIdea, ConceptEntry, BookNode, LearningPath
)


class TestGraphGeneratorInit:
    """GraphGenerator 初始化测试"""

    def test_init_default(self):
        """测试默认初始化"""
        generator = GraphGenerator()

        assert generator.config == {}

    def test_init_with_config(self):
        """测试带配置初始化"""
        config = {"test_key": "test_value"}
        generator = GraphGenerator(config)

        assert generator.config == config


class TestBookGraphMarkdown:
    """BookGraph Markdown 生成测试"""

    def _create_sample_book_graph(self) -> BookGraph:
        """创建测试用的 BookGraph"""
        return BookGraph(
            metadata=BookMetadata(
                title="测试书籍",
                author="测试作者",
                author_intro="这是一位测试作者的简介。",
                year_published="2024",
                category=["测试分类", "示例分类"],
                discipline=DisciplineType.哲学,
                tags=["测试", "示例", "自动化"],
                related_books=["关联书籍A", "关联书籍B"],
            ),
            time_background=TimeBackground(
                macro_background="这是一个宏观背景描述。",
                micro_background="这是作者的微观处境。",
                core_contradiction="核心矛盾在于...",
            ),
            chapters=[
                ChapterSummary(
                    chapter_number="1",
                    title="第一章 基础概念",
                    core_argument="本章讨论了基础概念的核心论点。",
                    underlying_logic="前提假设 → 推理链条 → 核心结论",
                    related_books=["相关书籍1"],
                    critical_questions=["问题1", "问题2"],
                )
            ],
            core_concepts=[
                CoreConcept(
                    name="核心概念A",
                    definition="这是核心概念A的定义。",
                    deep_meaning="深层含义在于...",
                    underlying_logic="底层逻辑拆解",
                    development_stages=[
                        {"name": "萌芽期", "period": "古代", "characteristics": ["特点A"]}
                    ],
                    core_drivers=["动力1", "动力2"],
                    critical_review="批判性审视内容",
                    related_books=["书籍X"],
                )
            ],
            key_insights=[
                KeyInsight(
                    title="关键洞见1",
                    description="这是洞见的描述内容。",
                    underlying_logic="洞见的底层逻辑",
                    deep_assumptions=["假设A", "假设B"],
                    related_books=["书籍Y"],
                    controversies="存在争议...",
                    multi_perspectives={"女性主义": "解读1", "后殖民": "解读2"},
                )
            ],
            key_cases=[
                KeyCase(
                    name="案例A",
                    source_chapter="第一章",
                    event_description="案例事件描述",
                    development_stages=[{"name": "阶段1", "description": "描述"}],
                    core_drivers=["动力A"],
                    related_books=["书籍Z"],
                    historical_limitations="历史局限性分析",
                )
            ],
            key_quotes=[
                KeyQuote(
                    text="这是一句重要的金句。",
                    chapter="第一章",
                    core_theme="核心主题",
                    background_context="时代背景关联",
                    underlying_logic="金句的底层逻辑",
                    common_misreading="常见误读分析",
                    related_books=["书籍W"],
                )
            ],
            critical_analysis=CriticalAnalysis(
                core_doubts=[{"question": "质疑1", "analysis": "分析1"}],
                feminist_perspective="女性主义视角分析",
                postcolonial_perspective="后殖民主义视角分析",
                ethical_boundaries={"reasonable": "合理应用", "dangerous": "危险应用"},
            ),
            learning_path={
                "beginner": ["入门书籍A"],
                "intermediate": ["进阶书籍B"],
                "advanced": ["深度书籍C"],
                "practice": ["实践D"],
            },
            book_network={"关联书籍1": "关联维度说明"},
        )

    def test_generate_book_graph_markdown_returns_string(self):
        """测试返回字符串"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        assert isinstance(markdown, str)
        assert len(markdown) > 0

    def test_yaml_front_matter(self):
        """测试 YAML Front Matter 格式"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查 YAML front matter
        assert markdown.startswith("---\n")
        assert "---\n" in markdown[:500]  # 第二个分隔符

        # 检查必需字段
        assert "title: 测试书籍" in markdown
        assert "author: 测试作者" in markdown
        assert "discipline: 哲学" in markdown

    def test_obsidian_internal_links(self):
        """测试 Obsidian [[链接]] 格式"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查内部链接格式
        assert "[[" in markdown
        assert "]]" in markdown

    def test_callout_syntax(self):
        """测试 Obsidian Callout 语法"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查 callout 格式：> [!type]
        callout_pattern = r'> \[!\w+\]'
        callouts = re.findall(callout_pattern, markdown)

        assert len(callouts) > 0  # 应有多个 callout

    def test_section_headers(self):
        """测试章节标题"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查主要章节标题
        assert "# 测试书籍" in markdown
        assert "## 📜 时代背景" in markdown
        assert "## 💡 核心概念" in markdown
        assert "## 🔍 关键洞见" in markdown

    def test_table_format(self):
        """测试表格格式"""
        generator = GraphGenerator()
        book_graph = self._create_sample_book_graph()

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查表格语法
        assert "| 章节 |" in markdown or "| 项目 |" in markdown
        assert "|------|" in markdown

    def test_empty_book_graph(self):
        """测试空 BookGraph"""
        generator = GraphGenerator()

        # 最小有效 BookGraph
        book_graph = BookGraph(
            metadata=BookMetadata(
                title="空书籍",
                author="未知作者",
                author_intro="",
                discipline=DisciplineType.哲学,
            ),
            time_background=TimeBackground(
                macro_background="",
                micro_background="",
                core_contradiction="",
            ),
            critical_analysis=CriticalAnalysis(
                feminist_perspective="",
                postcolonial_perspective="",
            ),
        )

        markdown = generator.generate_book_graph_markdown(book_graph)

        assert "# 空书籍" in markdown
        assert isinstance(markdown, str)


class TestDisciplineGraphMarkdown:
    """DisciplineGraph Markdown 生成测试"""

    def _create_sample_discipline_data(self) -> Dict:
        """创建测试用的学科数据"""
        return {
            "name": "哲学",
            "overview": {
                "definition": "哲学是研究基本问题的学科。",
                "scope": "涵盖形而上学、伦理学等领域。",
                "core_questions": ["什么是真理？", "如何定义善？"],
            }
        }

    def test_generate_discipline_graph_markdown_dict(self):
        """测试从 Dict 生成"""
        generator = GraphGenerator()
        data = self._create_sample_discipline_data()

        markdown = generator.generate_discipline_graph_markdown(data)

        assert isinstance(markdown, str)
        assert "# 哲学学科知识图谱" in markdown

    def test_discipline_yaml_front_matter(self):
        """测试学科图谱 YAML"""
        generator = GraphGenerator()
        data = self._create_sample_discipline_data()

        markdown = generator.generate_discipline_graph_markdown(data)

        assert "title: 哲学学科图谱" in markdown
        assert "type: discipline-graph" in markdown

    def test_discipline_sections(self):
        """测试学科图谱章节"""
        generator = GraphGenerator()
        data = self._create_sample_discipline_data()

        markdown = generator.generate_discipline_graph_markdown(data)

        # 检查主要章节
        assert "## 一、学科概述与核心问题" in markdown
        assert "## 二、学科整体知识结构" in markdown


class TestMarkdownEncoding:
    """Markdown 编码测试"""

    def test_chinese_characters(self):
        """测试中文字符处理"""
        generator = GraphGenerator()

        book_graph = BookGraph(
            metadata=BookMetadata(
                title="中文书籍标题",
                author="作者名",
                author_intro="作者简介包含中文",
                discipline=DisciplineType.哲学,
            ),
            time_background=TimeBackground(
                macro_background="宏观背景",
                micro_background="微观背景",
                core_contradiction="核心矛盾",
            ),
            critical_analysis=CriticalAnalysis(
                feminist_perspective="女性主义",
                postcolonial_perspective="后殖民",
            ),
        )

        markdown = generator.generate_book_graph_markdown(book_graph)

        # 检查中文未被转义
        assert "中文书籍标题" in markdown
        assert "作者名" in markdown

    def test_special_characters_escape(self):
        """测试特殊字符"""
        generator = GraphGenerator()

        book_graph = BookGraph(
            metadata=BookMetadata(
                title="书名<测试>",
                author="作者:测试",
                author_intro="简介",
                discipline=DisciplineType.哲学,
            ),
            time_background=TimeBackground(
                macro_background="背景",
                micro_background="处境",
                core_contradiction="矛盾",
            ),
            critical_analysis=CriticalAnalysis(
                feminist_perspective="视角",
                postcolonial_perspective="视角",
            ),
        )

        markdown = generator.generate_book_graph_markdown(book_graph)

        # Markdown 应正常生成（特殊字符在表格等位置可能需要处理）
        assert isinstance(markdown, str)
        assert len(markdown) > 0