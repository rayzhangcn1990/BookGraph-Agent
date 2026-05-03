"""
Skills 模块初始化

提供模块化内容生成能力：
- BaseSkill: Skill 基类
- ChapterSkill: 章节结构解析
- ConceptSkill: 核心概念提取
- InsightSkill: 关键洞见提取
- CaseSkill: 关键案例提取
- QuoteSkill: 金句萃取
- SkillOrchestrator: 并发协调器
"""

from core.skills.base_skill import BaseSkill, SkillResult
from core.skills.chapter_skill import ChapterSkill
from core.skills.concept_skill import ConceptSkill
from core.skills.insight_skill import InsightSkill
from core.skills.case_skill import CaseSkill
from core.skills.quote_skill import QuoteSkill
from core.skills.skill_orchestrator import SkillOrchestrator, BookProcessingResult

__all__ = [
    "BaseSkill",
    "SkillResult",
    "ChapterSkill",
    "ConceptSkill",
    "InsightSkill",
    "CaseSkill",
    "QuoteSkill",
    "SkillOrchestrator",
    "BookProcessingResult",
]