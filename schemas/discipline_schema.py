"""
Discipline Schema - 学科知识图谱数据结构定义

定义学科知识图谱的完整数据模型，包含 10 个核心板块。
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class DisciplineOverview(BaseModel):
    """学科概述"""
    name: str = Field(..., description="学科名称")
    core_questions: List[str] = Field(..., description="核心问题列表")
    definition: str = Field(..., description="学科定义")
    scope: str = Field(..., description="研究范围")


class KnowledgeStructure(BaseModel):
    """知识结构 - 树状图表示"""
    root: str = Field(..., description="根节点")
    branches: List[Dict[str, Any]] = Field(..., description="分支结构")
    tree_diagram: str = Field(..., description="ASCII 树状图")


class DevelopmentStage(BaseModel):
    """发展阶段"""
    name: str = Field(..., description="阶段名称")
    period: str = Field(..., description="时期")
    characteristics: List[str] = Field(..., description="阶段特点")
    evolution_reason: str = Field(..., description="进化/消亡原因")
    core_drivers: List[str] = Field(..., description="发展核心动力")


class CoreIdea(BaseModel):
    """核心思想"""
    name: str = Field(..., description="思想名称")
    definition: str = Field(..., description="定义")
    underlying_logic: str = Field(..., description="底层逻辑 - 三行格式：前提假设\\n推理链条\\n核心结论")
    key_proponents: List[str] = Field(default_factory=list, description="主要代表人物")
    related_concepts: List[str] = Field(default_factory=list, description="关联概念")


class ConceptEntry(BaseModel):
    """概念词条"""
    name: str = Field(..., description="概念名称")
    definition: str = Field(..., description="定义")
    source_book: str = Field(..., description="来源书籍")
    related_concepts: List[str] = Field(default_factory=list, description="关联概念")
    examples: List[str] = Field(default_factory=list, description="示例")


class BookNode(BaseModel):
    """书籍节点"""
    title: str = Field(..., description="书名")
    author: str = Field(..., description="作者")
    year: Optional[str] = Field(None, description="出版年份")
    relations: List[Dict[str, str]] = Field(default_factory=list, description="关联关系 - {目标书名：关联维度}")


class LearningPath(BaseModel):
    """学习路径"""
    beginner: List[str] = Field(..., description="初学者阶段 - 推荐书籍/资源")
    intermediate: List[str] = Field(..., description="进阶阶段")
    advanced: List[str] = Field(..., description="深度研究阶段")
    practice: List[str] = Field(..., description="实践应用建议")


class SchoolOfThought(BaseModel):
    """学派/流派"""
    name: str = Field(..., description="学派名称")
    core_claims: List[str] = Field(..., description="核心主张")
    key_figures: List[str] = Field(..., description="代表人物")
    debates_with: List[str] = Field(default_factory=list, description="争论对象")


class InterdisciplinaryLink(BaseModel):
    """跨学科关联"""
    discipline: str = Field(..., description="关联学科")
    intersection_areas: List[str] = Field(..., description="交叉领域")
    shared_methods: List[str] = Field(default_factory=list, description="共享方法")


class FrontierQuestion(BaseModel):
    """前沿问题"""
    question: str = Field(..., description="问题描述")
    current_status: str = Field(..., description="当前研究状态")
    key_researchers: List[str] = Field(default_factory=list, description="主要研究者")


class DisciplineGraph(BaseModel):
    """
    学科知识图谱 - 完整数据结构
    
    包含 10 个核心板块：
    1. 学科概述与核心问题
    2. 学科整体知识结构
    3. 学科发展脉络
    4. 学科核心思想及底层逻辑
    5. 核心概念词汇库
    6. 代表书籍与阅读网络
    7. 初学者入门指南
    8. 学科内部流派与争论
    9. 与其他学科的交叉关联
    10. 学科前沿与开放问题
    """
    overview: DisciplineOverview = Field(..., description="学科概述")
    knowledge_structure: KnowledgeStructure = Field(..., description="知识结构")
    development_stages: List[DevelopmentStage] = Field(default_factory=list, description="发展阶段")
    core_ideas: List[CoreIdea] = Field(default_factory=list, description="核心思想")
    concept_library: List[ConceptEntry] = Field(default_factory=list, description="概念词汇库")
    book_network: List[BookNode] = Field(default_factory=list, description="书籍网络")
    learning_path: LearningPath = Field(..., description="学习路径")
    schools_of_thought: List[SchoolOfThought] = Field(default_factory=list, description="学派流派")
    interdisciplinary_links: List[InterdisciplinaryLink] = Field(default_factory=list, description="跨学科关联")
    frontier_questions: List[FrontierQuestion] = Field(default_factory=list, description="前沿问题")
    
    # 元数据
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="创建时间")
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="更新时间")
    book_count: int = Field(default=0, description="收录书籍数量")
