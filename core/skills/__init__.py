"""
Skills 模块初始化

提供模块化内容生成能力：
- BaseSkill: Skill 基类
- BackgroundSkill: 时代背景提取
- ChapterSkill: 章节结构解析
- ConceptSkill: 核心概念提取
- InsightSkill: 关键洞见提取
- CaseSkill: 关键案例提取
- QuoteSkill: 金句萃取
- CriticalSkill: 批判性分析
- SkillOrchestrator: 并发协调器
"""

from core.skills.base_skill import BaseSkill, SkillResult
from core.skills.background_skill import BackgroundSkill
from core.skills.chapter_skill import ChapterSkill
from core.skills.concept_skill import ConceptSkill
from core.skills.insight_skill import InsightSkill
from core.skills.case_skill import CaseSkill
from core.skills.quote_skill import QuoteSkill
from core.skills.critical_skill import CriticalSkill
from core.skills.model_pool_skill import ModelPoolSkill
from core.skills.skill_orchestrator import SkillOrchestrator, BookProcessingResult

__all__ = [
    "BaseSkill",
    "SkillResult",
    "BackgroundSkill",
    "ChapterSkill",
    "ConceptSkill",
    "InsightSkill",
    "CaseSkill",
    "QuoteSkill",
    "CriticalSkill",
    "ModelPoolSkill",
    "SkillOrchestrator",
    "BookProcessingResult",
]