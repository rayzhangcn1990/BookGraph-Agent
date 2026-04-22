"""
Graph Generator - 知识图谱 Markdown 生成器

生成符合 Obsidian 标准的 Markdown 文件，包含完整的 Callout 语法和结构化内容。
"""

import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from schemas.book_graph_schema import BookGraph, DisciplineType
from schemas.discipline_schema import DisciplineGraph


class GraphGenerator:
    """
    知识图谱生成器
    
    功能：
    - 生成书籍知识图谱 Markdown
    - 生成学科知识图谱 Markdown
    - 使用 Obsidian 标准 Callout 语法
    - 包含完整的 8 层框架（书籍）和 10 板块（学科）
    """

    def __init__(self, config: Dict = None):
        """
        初始化生成器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}

    def _clean_placeholder(self, text: str, default: str = "") -> str:
        """
        清理 LLM 返回的占位符内容
        
        Args:
            text: 原始文本
            default: 默认替换值（空字符串表示直接移除）
            
        Returns:
            str: 清理后的文本
        """
        if not text:
            return default
        
        # 常见的占位符模式
        placeholders = [
            "待分析", "待补充", "待填写", "待生成",
            "TBD", "TODO", "N/A", "NULL", "None",
            "暂无", "无", "未涉及",
            "（此处内容由 LLM 生成）",
            "（内容由模型生成）",
        ]
        
        cleaned = text.strip()
        for ph in placeholders:
            if cleaned == ph or cleaned.startswith(ph) or ph in cleaned:
                return default
        
        return cleaned
    
    
    def generate_book_graph_markdown(self, book_graph: BookGraph) -> str:
        """
        生成书籍知识图谱 Markdown
        
        Args:
            book_graph: 书籍知识图谱对象
            
        Returns:
            str: 完整的 Markdown 内容
        """
        lines = []
        today = datetime.now().strftime("%Y-%m-%d")
        
        # ═══════════════════════════════════════════════════
        # Section 0: YAML Front Matter
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append(f"title: {book_graph.metadata.title}")
        lines.append(f"author: {book_graph.metadata.author}")
        lines.append(f"discipline: {book_graph.metadata.discipline.value}")
        
        if book_graph.metadata.year_published:
            lines.append(f"year: {book_graph.metadata.year_published}")
        
        lines.append("tags:")
        for tag in book_graph.metadata.tags:
            lines.append(f"  - {tag}")
        
        lines.append("category:")
        for cat in book_graph.metadata.category:
            lines.append(f"  - {cat}")
        
        lines.append("related_books:")
        for book in book_graph.metadata.related_books:
            lines.append(f'  - "[[{book}]]"')
        
        lines.append(f"created: {today}")
        lines.append("type: book-graph")
        lines.append("---")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 1: 书籍基础信息
        # ═══════════════════════════════════════════════════
        lines.append(f"> [!info] 作者简介")
        lines.append(f"> {book_graph.metadata.author_intro}")
        lines.append("")
        
        lines.append("| 项目 | 信息 |")
        lines.append("|------|------|")
        lines.append(f"| 作者 | {book_graph.metadata.author} |")
        if book_graph.metadata.year_published:
            lines.append(f"| 出版年份 | {book_graph.metadata.year_published} |")
        lines.append(f"| 学科 | {book_graph.metadata.discipline.value} |")
        lines.append(f"| 分类 | {', '.join(book_graph.metadata.category)} |")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 2: 时代背景
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 📜 时代背景")
        lines.append("")
        
        macro = self._clean_placeholder(book_graph.time_background.macro_background)
        micro = self._clean_placeholder(book_graph.time_background.micro_background)
        contradiction = self._clean_placeholder(book_graph.time_background.core_contradiction)
        
        lines.append(f"> [!quote] 宏观背景")
        lines.append(f"> {macro}")
        lines.append("")
        lines.append(f"> [!note] 微观背景")
        lines.append(f"> {micro}")
        lines.append("")
        lines.append("### 核心矛盾")
        lines.append("")
        lines.append("```")
        lines.append(contradiction)
        lines.append("```")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 3: 章节结构总览
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 📑 章节结构总览")
        lines.append("")
        lines.append("| 章节 | 主题 | 核心论点 | 底层逻辑 | 关联笔记 |")
        lines.append("|------|------|----------|----------|----------|")
        
        for chapter in book_graph.chapters:
            related = ", ".join([f"[[{b}]]" for b in chapter.related_books[:3]]) if chapter.related_books else "-"
            # 核心论点和底层逻辑保持完整，不截断，替换特殊字符避免破坏表格
            core_arg = chapter.core_argument.replace("|", "｜").replace("\n", " ").strip()
            logic = chapter.underlying_logic.replace("|", "｜").replace("\n", " ").strip()

            lines.append(
                f"| {chapter.chapter_number} | {chapter.title} | "
                f"{core_arg} | "
                f"{logic} | {related} |"
            )
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 4: 核心概念
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 💡 核心概念")
        lines.append("")
        
        for concept in book_graph.core_concepts:
            lines.append(f"### {concept.name}")
            lines.append("")
            lines.append(f"> [!abstract] 定义")
            lines.append(f"> {concept.definition}")
            lines.append("")
            
            if concept.deep_meaning:
                lines.append(f"**深层含义**：{concept.deep_meaning}")
                lines.append("")
            
            if concept.underlying_logic:
                lines.append("**底层逻辑**：")
                lines.append("")
                # 拆分为前提假设、推理链条、核心结论三行
                logic_text = concept.underlying_logic
                # 解析单行格式：前提假设：xxx→推理链条：xxx→核心结论：xxx
                m = re.match(r'前提假设：(.+?)→推理链条：(.+?)→核心结论：(.+)$', logic_text)
                if m:
                    lines.append(f"- **前提假设**：{m.group(1).strip()}")
                    lines.append(f"- **推理链条**：{m.group(2).strip()}")
                    lines.append(f"- **核心结论**：{m.group(3).strip()}")
                else:
                    # 已经是多行格式或其他格式，直接输出
                    for line_text in logic_text.split('\n'):
                        stripped = line_text.strip()
                        if stripped:
                            lines.append(f"- {stripped}")
                lines.append("")
            
            if concept.development_stages:
                lines.append("**发展演化**：")
                lines.append("")
                lines.append("| 阶段 | 时期 | 特点 | 消亡/进化原因 |")
                lines.append("|------|------|------|---------------|")
                for stage in concept.development_stages:
                    period = stage.get('period', '-')
                    characteristics = stage.get('characteristics', '-')
                    if isinstance(characteristics, list):
                        characteristics = ', '.join(characteristics)
                    reason = stage.get('evolution_reason', '-')
                    lines.append(f"| {stage.get('name', '-')} | {period} | {characteristics} | {reason} |")
                lines.append("")
            
            if concept.core_drivers:
                lines.append(f"> [!important] 发展核心动力")
                for driver in concept.core_drivers:
                    lines.append(f"> - {driver}")
                lines.append("")
            
            if concept.critical_review:
                lines.append(f"> [!warning] 批判性审视")
                lines.append(f"> {concept.critical_review}")
                lines.append("")
            
            if concept.related_books:
                lines.append(f"**关联书籍**：{', '.join([f'[[{b}]]' for b in concept.related_books])}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 5: 关键洞见
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 🔍 关键洞见")
        lines.append("")
        
        for insight in book_graph.key_insights:
            lines.append(f"### {insight.title}")
            lines.append("")
            lines.append(f"{insight.description}")
            lines.append("")
            
            if insight.underlying_logic:
                lines.append("**底层逻辑**：")
                lines.append("")
                # 拆分为前提假设、推理链条、核心结论三行
                logic_text = insight.underlying_logic
                m = re.match(r'前提假设：(.+?)→推理链条：(.+?)→核心结论：(.+)$', logic_text)
                if m:
                    lines.append(f"- **前提假设**：{m.group(1).strip()}")
                    lines.append(f"- **推理链条**：{m.group(2).strip()}")
                    lines.append(f"- **核心结论**：{m.group(3).strip()}")
                else:
                    for line_text in logic_text.split('\n'):
                        stripped = line_text.strip()
                        if stripped:
                            lines.append(f"- {stripped}")
                lines.append("")
            
            if insight.deep_assumptions:
                lines.append("**深层假设**：")
                lines.append("")
                for assumption in insight.deep_assumptions:
                    # 清理假设中的特殊字符
                    clean_assumption = assumption.replace("|", "｜").strip() if isinstance(assumption, str) else str(assumption)
                    lines.append(f"- {clean_assumption}")
                lines.append("")
            
            if insight.multi_perspectives:
                lines.append("**多维审视**：")
                lines.append("")
                lines.append("| 视角 | 解读 |")
                lines.append("|------|------|")
                for perspective, interpretation in insight.multi_perspectives.items():
                    lines.append(f"| {perspective} | {interpretation} |")
                lines.append("")
            
            if insight.controversies:
                lines.append(f"> [!question] 潜在争议")
                lines.append(f"> {insight.controversies}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 6: 关键案例
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 📚 关键案例")
        lines.append("")
        
        for case in book_graph.key_cases:
            lines.append(f"### {case.name}")
            lines.append("")
            lines.append(f"> [!example] 基本信息")
            lines.append(f"> **来源**：{case.source_chapter}")
            lines.append(f"> {case.event_description}")
            lines.append("")
            
            if case.development_stages:
                lines.append("**发展阶段**：")
                lines.append("```")
                for i, stage in enumerate(case.development_stages, 1):
                    stage_name = stage.get('name', f'阶段{i}')
                    stage_desc = stage.get('description', '')
                    lines.append(f"{i}. {stage_name}: {stage_desc}")
                lines.append("```")
                lines.append("")
            
            if case.core_drivers:
                lines.append(f"**核心动力**：{', '.join(case.core_drivers)}")
                lines.append("")
            
            if case.historical_limitations:
                lines.append(f"> [!warning] 历史局限性")
                lines.append(f"> {case.historical_limitations}")
                lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 7: 金句萃取
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## ✨ 金句萃取")
        lines.append("")
        
        for quote in book_graph.key_quotes:
            lines.append(f"> \"{quote.text}\"")
            lines.append(f"> —— {book_graph.metadata.author}，《{book_graph.metadata.title}》{quote.chapter}")
            lines.append("")
            
            lines.append("| 要素 | 内容 |")
            lines.append("|------|------|")
            lines.append(f"| 时代背景 | {quote.background_context} |")
            lines.append(f"| 底层逻辑 | {quote.underlying_logic} |")
            lines.append(f"| 完整语境 | {quote.core_theme} |")
            if quote.common_misreading:
                lines.append(f"| 常见误读 | {quote.common_misreading} |")
            if quote.related_books:
                lines.append(f"| 关联笔记 | {', '.join([f'[[{b}]]' for b in quote.related_books])} |")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 8: 批判性解读
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 🤔 批判性解读")
        lines.append("")
        
        if book_graph.critical_analysis.core_doubts:
            lines.append(f"> [!question] 核心质疑")
            for doubt in book_graph.critical_analysis.core_doubts:
                if isinstance(doubt, dict):
                    question = doubt.get('question', '')
                    analysis = doubt.get('analysis', '')
                    lines.append(f"> - **{question}**")
                    if analysis:
                        lines.append(f">   {analysis}")
                else:
                    lines.append(f"> - {doubt}")
            lines.append("")
        
        lines.append("### 多元视角分析")
        lines.append("")
        lines.append(f"**女性主义视角**：{book_graph.critical_analysis.feminist_perspective}")
        lines.append("")
        lines.append(f"**后殖民主义视角**：{book_graph.critical_analysis.postcolonial_perspective}")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 9: 伦理边界
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## ⚖️ 伦理边界")
        lines.append("")
        
        ethical = book_graph.critical_analysis.ethical_boundaries
        
        if ethical.get('reasonable'):
            lines.append(f"> [!check] 合理应用区间")
            lines.append(f"> {ethical['reasonable']}")
            lines.append("")
        
        if ethical.get('dangerous'):
            lines.append(f"> [!danger] 危险应用区间")
            lines.append(f"> {ethical['dangerous']}")
            lines.append("")
        
        if ethical.get('institutional_safeguards'):
            lines.append("**制度性防范机制**：")
            lines.append("")
            lines.append("| 机制 | 说明 |")
            lines.append("|------|------|")
            safeguards = ethical['institutional_safeguards']
            if isinstance(safeguards, str):
                lines.append(f"| 防范措施 | {safeguards} |")
            elif isinstance(safeguards, list):
                for s in safeguards:
                    lines.append(f"| {s} | - |")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 10: 学习路径
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 📖 学习路径")
        lines.append("")
        lines.append("```")
        
        learning_path = book_graph.learning_path
        if learning_path:
            lines.append("初学者 → 进阶 → 深度研究 → 实践应用")
            lines.append("")
            
            if 'beginner' in learning_path:
                lines.append("【初学者】")
                for item in learning_path['beginner']:
                    lines.append(f"  - {item}")
                lines.append("")
            
            if 'intermediate' in learning_path:
                lines.append("【进阶】")
                for item in learning_path['intermediate']:
                    lines.append(f"  - {item}")
                lines.append("")
            
            if 'advanced' in learning_path:
                lines.append("【深度研究】")
                for item in learning_path['advanced']:
                    lines.append(f"  - {item}")
                lines.append("")
            
            if 'practice' in learning_path:
                lines.append("【实践应用】")
                for item in learning_path['practice']:
                    lines.append(f"  - {item}")
        else:
            lines.append("初学者 → 进阶 → 深度研究 → 实践应用")
            lines.append("（学习路径待补充）")
        
        lines.append("```")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 11: 关联书籍网络
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 🔗 关联书籍网络")
        lines.append("")
        lines.append(f"**本书**：[[{book_graph.metadata.title}]]")
        lines.append("")
        lines.append("| 关联书籍 | 关联维度说明 |")
        lines.append("|----------|-------------|")
        
        for related_book, relation in book_graph.book_network.items():
            # 清理关联说明中的特殊字符
            clean_relation = relation.replace("|", "｜").replace("\n", " ")
            lines.append(f"| [[{related_book}]] | {clean_relation} |")
        
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # Section 12: 页脚
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append(f"*所属学科*：[[{book_graph.metadata.discipline.value}学科图谱]]")
        lines.append(f"*最后更新*：{today}")
        lines.append("*图谱类型*：书籍知识图谱")
        
        return "\n".join(lines)

    def generate_discipline_graph_markdown(self, discipline_data: Dict) -> str:
        """
        生成学科知识图谱 Markdown
        
        Args:
            discipline_data: 学科图谱数据（Dict 或 DisciplineGraph）
            
        Returns:
            str: 完整的 Markdown 内容
        """
        lines = []
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 提取学科名称
        if isinstance(discipline_data, DisciplineGraph):
            discipline_name = discipline_data.overview.name
            overview = discipline_data.overview
        else:
            discipline_name = discipline_data.get('name', '学科')
            overview = discipline_data.get('overview', {})
        
        # ═══════════════════════════════════════════════════
        # YAML Front Matter
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append(f"title: {discipline_name}学科图谱")
        lines.append(f"type: discipline-graph")
        lines.append(f"created: {today}")
        lines.append(f"updated: {today}")
        lines.append("---")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 一、学科概述与核心问题
        # ═══════════════════════════════════════════════════
        lines.append(f"# {discipline_name}学科知识图谱")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 一、学科概述与核心问题")
        lines.append("")
        
        if isinstance(overview, dict):
            lines.append(f"**定义**：{overview.get('definition', '待补充')}")
            lines.append("")
            lines.append(f"**研究范围**：{overview.get('scope', '待补充')}")
            lines.append("")
            lines.append("**核心问题**：")
            for q in overview.get('core_questions', []):
                lines.append(f"- {q}")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 二、学科整体知识结构
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 二、学科整体知识结构")
        lines.append("")
        lines.append("```")
        
        if isinstance(discipline_data, DisciplineGraph) and discipline_data.knowledge_structure:
            lines.append(discipline_data.knowledge_structure.tree_diagram)
        else:
            lines.append(f"{discipline_name}")
            lines.append("├── 分支领域 1")
            lines.append("│   ├── 子领域 1.1")
            lines.append("│   └── 子领域 1.2")
            lines.append("├── 分支领域 2")
            lines.append("└── 分支领域 3")
        
        lines.append("```")
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 三、学科发展脉络
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 三、学科发展脉络")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            for stage in discipline_data.development_stages:
                lines.append(f"### {stage.name}（{stage.period}）")
                lines.append("")
                lines.append(f"**特点**：{', '.join(stage.characteristics)}")
                lines.append("")
                lines.append(f"**进化/消亡原因**：{stage.evolution_reason}")
                lines.append("")
                lines.append(f"**核心动力**：{', '.join(stage.core_drivers)}")
                lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("（发展脉络待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 四、学科核心思想及底层逻辑
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 四、学科核心思想及底层逻辑")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            for idea in discipline_data.core_ideas:
                lines.append(f"### {idea.name}")
                lines.append("")
                lines.append(f"**定义**：{idea.definition}")
                lines.append("")
                lines.append("**底层逻辑**：")
                lines.append("")
                # 拆分为前提假设、推理链条、核心结论三行
                logic_text = idea.underlying_logic
                m = re.match(r'前提假设：(.+?)→推理链条：(.+?)→核心结论：(.+)$', logic_text)
                if m:
                    lines.append(f"- **前提假设**：{m.group(1).strip()}")
                    lines.append(f"- **推理链条**：{m.group(2).strip()}")
                    lines.append(f"- **核心结论**：{m.group(3).strip()}")
                else:
                    for line_text in logic_text.split('\n'):
                        stripped = line_text.strip()
                        if stripped:
                            lines.append(f"- {stripped}")
                lines.append("")
                
                if idea.key_proponents:
                    lines.append(f"**代表人物**：{', '.join(idea.key_proponents)}")
                    lines.append("")
        else:
            lines.append("（核心思想待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 五、核心概念词汇库
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 五、核心概念词汇库")
        lines.append("")
        lines.append("| 概念 | 定义 | 来源书籍 | 关联概念 |")
        lines.append("|------|------|----------|----------|")
        
        if isinstance(discipline_data, DisciplineGraph):
            for concept in discipline_data.concept_library:
                related = ', '.join(concept.related_concepts[:3]) if concept.related_concepts else '-'
                lines.append(
                    f"| {concept.name} | {concept.definition[:30]}... | "
                    f"[[{concept.source_book}]] | {related} |"
                )
        else:
            lines.append("| 待补充 | 待补充 | - | - |")
        
        lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 六、代表书籍与阅读网络
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 六、代表书籍与阅读网络")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph) and discipline_data.book_network:
            for book in discipline_data.book_network:
                lines.append(f"### [[{book.title}]]")
                lines.append(f"**作者**：{book.author}")
                if book.year:
                    lines.append(f"**出版年份**：{book.year}")
                lines.append("")
                
                if book.relations:
                    lines.append("**关联关系**：")
                    for rel in book.relations:
                        for target, dimension in rel.items():
                            lines.append(f"- 与 [[{target}]]：{dimension}")
                lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("（书籍网络待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 七、初学者入门指南
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 七、初学者入门指南")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            lp = discipline_data.learning_path
            
            lines.append("### 学习路径")
            lines.append("")
            lines.append("```")
            lines.append("初学者 → 进阶 → 深度研究 → 实践应用")
            lines.append("```")
            lines.append("")
            
            if lp.beginner:
                lines.append("**初学者阶段**：")
                for item in lp.beginner:
                    lines.append(f"- {item}")
                lines.append("")
            
            if lp.intermediate:
                lines.append("**进阶阶段**：")
                for item in lp.intermediate:
                    lines.append(f"- {item}")
                lines.append("")
            
            if lp.advanced:
                lines.append("**深度研究阶段**：")
                for item in lp.advanced:
                    lines.append(f"- {item}")
                lines.append("")
            
            if lp.practice:
                lines.append("**实践应用**：")
                for item in lp.practice:
                    lines.append(f"- {item}")
                lines.append("")
        else:
            lines.append("（入门指南待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 八、学科内部流派与争论
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 八、学科内部流派与争论")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            for school in discipline_data.schools_of_thought:
                lines.append(f"### {school.name}")
                lines.append("")
                lines.append(f"**核心主张**：")
                for claim in school.core_claims:
                    lines.append(f"- {claim}")
                lines.append("")
                
                if school.key_figures:
                    lines.append(f"**代表人物**：{', '.join(school.key_figures)}")
                    lines.append("")
                
                if school.debates_with:
                    lines.append(f"**争论对象**：{', '.join(school.debates_with)}")
                    lines.append("")
                
                lines.append("---")
                lines.append("")
        else:
            lines.append("（流派与争论待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 九、与其他学科的交叉关联
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 九、与其他学科的交叉关联")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            for link in discipline_data.interdisciplinary_links:
                lines.append(f"### {link.discipline}")
                lines.append("")
                lines.append(f"**交叉领域**：{', '.join(link.intersection_areas)}")
                lines.append("")
                
                if link.shared_methods:
                    lines.append(f"**共享方法**：{', '.join(link.shared_methods)}")
                    lines.append("")
                
                lines.append("---")
                lines.append("")
        else:
            lines.append("（交叉关联待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 十、学科前沿与开放问题
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append("## 十、学科前沿与开放问题")
        lines.append("")
        
        if isinstance(discipline_data, DisciplineGraph):
            for fq in discipline_data.frontier_questions:
                lines.append(f"### {fq.question}")
                lines.append("")
                lines.append(f"**当前研究状态**：{fq.current_status}")
                lines.append("")
                
                if fq.key_researchers:
                    lines.append(f"**主要研究者**：{', '.join(fq.key_researchers)}")
                    lines.append("")
                
                lines.append("---")
                lines.append("")
        else:
            lines.append("（前沿问题待补充）")
            lines.append("")
        
        # ═══════════════════════════════════════════════════
        # 页脚
        # ═══════════════════════════════════════════════════
        lines.append("---")
        lines.append("")
        lines.append(f"*最后更新*：{today}")
        lines.append("*图谱类型*：学科知识图谱")
        
        return "\n".join(lines)
