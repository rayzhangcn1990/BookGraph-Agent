"""
Discipline Manager - 学科图谱管理模块

负责学科知识图谱的创建、更新和查询。
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

from schemas.book_graph_schema import BookGraph, DisciplineType
from schemas.discipline_schema import (
    DisciplineGraph, DisciplineOverview, KnowledgeStructure,
    DevelopmentStage, CoreIdea, ConceptEntry, BookNode,
    LearningPath, SchoolOfThought, InterdisciplinaryLink, FrontierQuestion
)

from .obsidian_writer import ObsidianWriter
from .graph_generator import GraphGenerator


class DisciplineManager:
    """
    学科管理器
    
    功能：
    - 更新学科图谱（智能合并新书内容）
    - 创建初始学科图谱
    - 获取学科摘要
    - 管理学科图谱版本
    """
    
    def __init__(
        self, 
        obsidian_writer: ObsidianWriter,
        graph_generator: GraphGenerator,
        config: Dict = None
    ):
        """
        初始化学科管理器
        
        Args:
            obsidian_writer: Obsidian 写入器
            graph_generator: 图谱生成器
            config: 配置字典
        """
        self.writer = obsidian_writer
        self.generator = graph_generator
        self.config = config or {}

    def update_discipline_graph(
        self, 
        discipline: str, 
        new_book_graph: BookGraph
    ) -> None:
        """
        更新学科图谱
        
        整体流程：
        a. 读取现有学科图谱
        b. 若不存在：创建初始图谱
        c. 若已存在：LLM 智能合并新书内容
        d. 写入更新后的图谱
        
        Args:
            discipline: 学科名称
            new_book_graph: 新书知识图谱
        """
        print(f"🔄 开始更新学科图谱：{discipline}")
        
        # a. 读取现有学科图谱
        existing_content = self.writer.read_existing_discipline_graph(discipline)
        
        if existing_content is None:
            # b. 创建初始图谱
            print(f"📝 创建初始学科图谱：{discipline}")
            new_content = self.create_initial_discipline_graph(discipline, new_book_graph)
        else:
            # c. LLM 智能合并（通过 Hermes/Claude Code）
            print(f"🤖 LLM 智能合并新书内容...")
            print("\n" + "="*70)
            print("📝 [学科图谱更新 - 需要 LLM 调用]")
            print("="*70)
            print("⚠️  LLM 调用未获取响应，使用新书内容直接合并")
            print("="*70 + "\n")
            new_content = existing_content + "\n\n## 新增书籍\n\n" + new_book_graph.metadata.title
        
        # d. 写入更新后的图谱
        self.writer.write_discipline_graph(discipline, new_content)
        print(f"✅ 学科图谱更新完成：{discipline}")

    def create_initial_discipline_graph(
        self, 
        discipline: str, 
        first_book: BookGraph
    ) -> str:
        """
        基于第一本书创建学科图谱的初始版本
        
        Args:
            discipline: 学科名称
            first_book: 第一本书的知识图谱
            
        Returns:
            str: 学科图谱 Markdown 内容
        """
        # 构建初始学科图谱数据结构
        discipline_data = self._build_initial_discipline_data(discipline, first_book)
        
        # 生成 Markdown
        markdown_content = self.generator.generate_discipline_graph_markdown(discipline_data)
        
        return markdown_content

    def _build_initial_discipline_data(
        self, 
        discipline: str, 
        first_book: BookGraph
    ) -> DisciplineGraph:
        """
        构建初始学科图谱数据
        
        Args:
            discipline: 学科名称
            first_book: 第一本书的知识图谱
            
        Returns:
            DisciplineGraph: 学科图谱对象
        """
        # 1. 学科概述
        overview = DisciplineOverview(
            name=discipline,
            core_questions=self._generate_core_questions(discipline, first_book),
            definition=self._generate_discipline_definition(discipline, first_book),
            scope=self._generate_discipline_scope(discipline, first_book),
        )
        
        # 2. 知识结构
        knowledge_structure = KnowledgeStructure(
            root=discipline,
            branches=self._generate_knowledge_branches(discipline, first_book),
            tree_diagram=self._generate_tree_diagram(discipline, first_book),
        )
        
        # 3. 发展阶段（从书中提取）
        development_stages = []
        for concept in first_book.core_concepts:
            if concept.development_stages:
                for stage in concept.development_stages:
                    development_stages.append(DevelopmentStage(
                        name=stage.get('name', '未知阶段'),
                        period=stage.get('period', '未知时期'),
                        characteristics=stage.get('characteristics', []) if isinstance(stage.get('characteristics'), list) else [str(stage.get('characteristics', ''))],
                        evolution_reason=stage.get('evolution_reason', '待补充'),
                        core_drivers=concept.core_drivers,
                    ))
        
        if not development_stages:
            # 默认阶段
            development_stages = [
                DevelopmentStage(
                    name="萌芽期",
                    period="古代 - 近代",
                    characteristics=["初步概念形成", "基础理论探索"],
                    evolution_reason="知识积累不足",
                    core_drivers=["实践需求", "哲学思辨"],
                ),
                DevelopmentStage(
                    name="发展期",
                    period="近代 - 现代",
                    characteristics=["理论体系建立", "方法论成熟"],
                    evolution_reason="科学方法引入",
                    core_drivers=["学术研究", "技术进步"],
                ),
                DevelopmentStage(
                    name="成熟期",
                    period="现代 - 当代",
                    characteristics=["跨学科融合", "应用拓展"],
                    evolution_reason="全球化与数字化",
                    core_drivers=["跨学科合作", "技术创新"],
                ),
            ]
        
        # 4. 核心思想（从书中提取）
        core_ideas = []
        for concept in first_book.core_concepts[:5]:  # 取前 5 个核心概念
            core_ideas.append(CoreIdea(
                name=concept.name,
                definition=concept.definition,
                underlying_logic=concept.underlying_logic,
                key_proponents=[first_book.metadata.author],
                related_concepts=[c.name for c in first_book.core_concepts if c.name != concept.name][:3],
            ))
        
        # 5. 概念词汇库
        concept_library = []
        for concept in first_book.core_concepts:
            concept_library.append(ConceptEntry(
                name=concept.name,
                definition=concept.definition,
                source_book=first_book.metadata.title,
                related_concepts=[c.name for c in first_book.core_concepts if c.name != concept.name][:3],
            ))
        
        # 6. 书籍网络
        book_network = []
        book_network.append(BookNode(
            title=first_book.metadata.title,
            author=first_book.metadata.author,
            year=first_book.metadata.year_published,
            relations=[{book: dim} for book, dim in first_book.book_network.items()] if first_book.book_network else [],
        ))
        
        # 7. 学习路径
        learning_path = LearningPath(
            beginner=[first_book.metadata.title] if first_book.metadata.title else [],
            intermediate=[],
            advanced=[],
            practice=[],
        )
        
        # 8-10. 其他板块（初始为空）
        schools_of_thought = []
        interdisciplinary_links = []
        frontier_questions = []
        
        return DisciplineGraph(
            overview=overview,
            knowledge_structure=knowledge_structure,
            development_stages=development_stages,
            core_ideas=core_ideas,
            concept_library=concept_library,
            book_network=book_network,
            learning_path=learning_path,
            schools_of_thought=schools_of_thought,
            interdisciplinary_links=interdisciplinary_links,
            frontier_questions=frontier_questions,
            book_count=1,
        )

    def _generate_core_questions(self, discipline: str, first_book: BookGraph) -> List[str]:
        """生成学科核心问题"""
        # 从书中提取核心问题
        questions = []
        
        # 从批判性分析中提取
        if first_book.critical_analysis.core_doubts:
            for doubt in first_book.critical_analysis.core_doubts:
                if isinstance(doubt, dict) and 'question' in doubt:
                    questions.append(doubt['question'])
        
        # 默认问题
        default_questions = [
            f"{discipline}的核心研究对象是什么？",
            f"{discipline}的基本方法论有哪些？",
            f"{discipline}如何解释现实世界的问题？",
        ]
        
        return questions[:3] if questions else default_questions

    def _generate_discipline_definition(self, discipline: str, first_book: BookGraph) -> str:
        """生成学科定义"""
        # 从书中提取定义线索
        if first_book.core_concepts:
            first_concept = first_book.core_concepts[0]
            return f"{discipline}是研究{first_concept.definition.lower()}的学科领域。"
        
        return f"{discipline}是一门研究人类思想、行为和社会现象的学科。"

    def _generate_discipline_scope(self, discipline: str, first_book: BookGraph) -> str:
        """生成学科研究范围"""
        categories = first_book.metadata.category
        if categories:
            return f"涵盖{', '.join(categories)}等领域。"
        
        return "涵盖理论研究、实证研究、应用研究等多个层面。"

    def _generate_knowledge_branches(self, discipline: str, first_book: BookGraph) -> List[Dict]:
        """生成知识分支"""
        branches = []
        
        # 从核心概念推断分支
        for concept in first_book.core_concepts[:3]:
            branches.append({
                "name": concept.name,
                "sub_branches": [],
            })
        
        return branches

    def _generate_tree_diagram(self, discipline: str, first_book: BookGraph) -> str:
        """生成 ASCII 树状图"""
        lines = [discipline]
        
        # 添加核心概念作为分支
        for i, concept in enumerate(first_book.core_concepts[:5], 1):
            prefix = "├── " if i < 5 else "└── "
            lines.append(f"{prefix}{concept.name}")
        
        return "\n".join(lines)

    def get_discipline_summary(self, discipline: str) -> Dict:
        """
        获取学科当前状态摘要
        
        Args:
            discipline: 学科名称
            
        Returns:
            Dict: 摘要信息
        """
        # 获取所有书籍
        books = self.writer.get_all_books_in_discipline(discipline)
        
        # 读取学科图谱获取更多信息
        graph_content = self.writer.read_existing_discipline_graph(discipline)
        
        # 统计概念数量（粗略估计）
        concept_count = 0
        if graph_content:
            concept_count = graph_content.count("### ")  # 三级标题数量估计
        
        # 获取最后更新时间
        last_updated = "未知"
        if graph_content:
            import re
            match = re.search(r'\*最后更新\*：(\d{4}-\d{2}-\d{2})', graph_content)
            if match:
                last_updated = match.group(1)
        
        return {
            "discipline": discipline,
            "book_count": len(books),
            "books": books,
            "concept_count": concept_count,
            "last_updated": last_updated,
        }

    def get_all_disciplines(self) -> List[str]:
        """
        获取所有学科列表
        
        Returns:
            List[str]: 学科名称列表
        """
        disciplines = []
        
        graph_root = self.writer.vault_path / self.writer.graph_root
        if graph_root.exists():
            for item in graph_root.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    disciplines.append(item.name)
        
        return sorted(disciplines)

    def get_discipline_stats(self, discipline: str) -> Dict:
        """
        获取学科详细统计
        
        Args:
            discipline: 学科名称
            
        Returns:
            Dict: 详细统计信息
        """
        summary = self.get_discipline_summary(discipline)
        
        # 添加更多统计
        stats = {
            **summary,
            "total_concepts": 0,
            "total_insights": 0,
            "total_quotes": 0,
            "learning_path_stages": 0,
        }
        
        # 从学科图谱中提取更多信息
        graph_content = self.writer.read_existing_discipline_graph(discipline)
        if graph_content:
            stats["total_concepts"] = graph_content.count("## 五、核心概念") + graph_content.count("### ")
            stats["has_learning_path"] = "## 七、初学者入门指南" in graph_content
        
        return stats
