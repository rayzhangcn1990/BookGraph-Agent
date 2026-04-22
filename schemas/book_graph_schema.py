"""
BookGraph Schema - 书籍知识图谱数据结构定义

定义完整的 Pydantic 数据模型，用于书籍知识图谱的结构化表示。
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class DisciplineType(str, Enum):
    """一级学科类型枚举"""
    政治学 = "政治学"
    经济学 = "经济学"
    心理学 = "心理学"
    历史学 = "历史学"
    哲学 = "哲学"
    管理学 = "管理学"
    社会学 = "社会学"
    文学 = "文学"
    科学 = "科学"
    技术 = "技术"


# 子学科映射 - 一级学科下的二级分类
SUB_DISCIPLINES = {
    "政治学": ["政治哲学", "比较政治", "国际关系", "政治经济学", "公共行政", "政治理论"],
    "经济学": ["微观经济学", "宏观经济学", "政治经济学", "发展经济学", "行为经济学"],
    "哲学": ["政治哲学", "伦理学", "形而上学", "认识论", "美学"],
    "历史学": ["政治史", "经济史", "思想史", "世界史", "中国史"],
    "社会学": ["政治社会学", "经济社会学", "文化社会学", "组织社会学"],
    # 其他学科可按需扩展
}


class BookMetadata(BaseModel):
    """书籍元数据"""
    title: str = Field(..., description="书名")
    author: str = Field(..., description="作者")
    author_intro: str = Field(..., description="作者简介")
    year_published: Optional[str] = Field(None, description="出版年份")
    category: List[str] = Field(default_factory=list, description="分类标签")
    discipline: DisciplineType = Field(..., description="所属一级学科")
    sub_discipline: Optional[str] = Field(None, description="所属二级子学科（如：政治哲学属于政治学）")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")


class TimeBackground(BaseModel):
    """时代背景分析"""
    macro_background: str = Field(..., description="宏观背景 - 时代大环境")
    micro_background: str = Field(..., description="微观背景 - 作者个人处境")
    core_contradiction: str = Field(..., description="核心矛盾 - 时代核心问题")


class ChapterSummary(BaseModel):
    """章节摘要"""
    chapter_number: str = Field(..., description="章节编号")
    title: str = Field(..., description="章节标题")
    core_argument: str = Field(..., description="核心论点")
    underlying_logic: str = Field(..., description="底层逻辑 - 三行格式：前提假设\\n推理链条\\n核心结论")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")
    critical_questions: List[str] = Field(default_factory=list, description="批判性问题列表")


class CoreConcept(BaseModel):
    """核心概念"""
    name: str = Field(..., description="概念名称")
    definition: str = Field(..., description="定义")
    deep_meaning: str = Field(..., description="深层含义")
    underlying_logic: str = Field(..., description="底层逻辑拆解")
    development_stages: List[Dict[str, Any]] = Field(default_factory=list, description="发展阶段列表")
    core_drivers: List[str] = Field(default_factory=list, description="发展核心动力")
    critical_review: str = Field(..., description="批判性审视")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")


class KeyInsight(BaseModel):
    """关键洞见"""
    title: str = Field(..., description="洞见标题")
    description: str = Field(..., description="洞见描述")
    underlying_logic: str = Field(..., description="底层逻辑")
    deep_assumptions: List[str] = Field(default_factory=list, description="深层假设列表")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")
    controversies: str = Field(..., description="潜在争议")
    multi_perspectives: Dict[str, str] = Field(default_factory=dict, description="多维审视 - 视角：解读")


class KeyCase(BaseModel):
    """关键案例"""
    name: str = Field(..., description="案例名称")
    source_chapter: str = Field(..., description="来源章节")
    event_description: str = Field(..., description="事件描述")
    development_stages: List[Dict[str, Any]] = Field(default_factory=list, description="案例发展阶段分析")
    core_drivers: List[str] = Field(default_factory=list, description="发展核心动力")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")
    historical_limitations: str = Field(..., description="历史局限性")


class KeyQuote(BaseModel):
    """金句"""
    text: str = Field(..., description="金句原文")
    chapter: str = Field(..., description="来源章节")
    core_theme: str = Field(..., description="核心主题")
    background_context: str = Field(..., description="时代背景关联")
    underlying_logic: str = Field(..., description="底层逻辑")
    common_misreading: Optional[str] = Field(None, description="常见误读")
    related_books: List[str] = Field(default_factory=list, description="关联书籍")


class CriticalAnalysis(BaseModel):
    """批判性分析"""
    core_doubts: List[Dict[str, Any]] = Field(default_factory=list, description="核心质疑列表")
    feminist_perspective: str = Field(..., description="女性主义视角")
    postcolonial_perspective: str = Field(..., description="后殖民主义视角")
    ethical_boundaries: Dict[str, str] = Field(default_factory=dict, description="伦理边界")


class BookGraph(BaseModel):
    """
    书籍知识图谱 - 完整数据结构
    
    包含 8 层框架：
    1. 书籍基础信息层
    2. 章节结构与核心内容
    3. 知识点提炼层
    4. 关键洞见与多维审视
    5. 关键案例与动态链接
    6. 金句萃取与语境化解读
    7. 学习路径与跨书籍链接
    8. 批判性解读与多维审视
    """
    metadata: BookMetadata = Field(..., description="书籍元数据")
    time_background: TimeBackground = Field(..., description="时代背景")
    chapters: List[ChapterSummary] = Field(default_factory=list, description="章节摘要列表")
    core_concepts: List[CoreConcept] = Field(default_factory=list, description="核心概念列表")
    key_insights: List[KeyInsight] = Field(default_factory=list, description="关键洞见列表")
    key_cases: List[KeyCase] = Field(default_factory=list, description="关键案例列表")
    key_quotes: List[KeyQuote] = Field(default_factory=list, description="金句列表")
    critical_analysis: CriticalAnalysis = Field(..., description="批判性分析")
    learning_path: Dict[str, List[str]] = Field(default_factory=dict, description="学习路径")
    book_network: Dict[str, str] = Field(default_factory=dict, description="书籍网络 - 书名：关联维度")

    class Config:
        json_schema_extra = {
            "example": {
                "metadata": {
                    "title": "君主论",
                    "author": "尼科洛·马基雅维利",
                    "author_intro": "意大利文艺复兴时期政治思想家",
                    "year_published": "1532",
                    "category": ["政治哲学", "经典著作"],
                    "discipline": "政治学",
                    "sub_discipline": "政治哲学",
                    "tags": ["权力", "统治", "政治现实主义"],
                    "related_books": ["理想国", "利维坦"]
                }
            }
        }
