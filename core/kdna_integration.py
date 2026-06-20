"""
KDNA Assets集成模块

将BookGraph质量检查规则和生成流程集成到KDNA判断资产格式
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

# KDNA资产路径
KDNA_ASSETS_PATH = Path(__file__).parent.parent / "kdna-assets"


class KDNAQualityChecker:
    """
    KDNA质量检查器

    加载@bookgraph/quality-checks判断资产，执行标准化质量检查
    """

    def __init__(self):
        """初始化KDNA质量检查器"""
        self.manifest = self._load_manifest()
        self.truth_charter = self._load_truth_charter()
        self.axioms = self.manifest.get('axioms', [])

    def _load_manifest(self) -> Dict:
        """加载质量检查manifest"""
        manifest_path = KDNA_ASSETS_PATH / "@bookgraph/quality-checks/manifest.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding='utf-8'))
        return {}

    def _load_truth_charter(self) -> Dict:
        """加载Truth Charter"""
        charter_path = KDNA_ASSETS_PATH / "@bookgraph/quality-checks/truth_charter.json"
        if charter_path.exists():
            return json.loads(charter_path.read_text(encoding='utf-8'))
        return {}

    def get_axiom(self, axiom_id: str) -> Optional[Dict]:
        """
        获取指定axiom

        Args:
            axiom_id: axiom ID（如'no-placeholder-pollution'）

        Returns:
            Optional[Dict]: axiom定义
        """
        for axiom in self.axioms:
            if axiom.get('id') == axiom_id:
                return axiom
        return None

    def get_all_axioms(self) -> List[Dict]:
        """获取所有axioms"""
        return self.axioms

    def validate_boundaries(self, data: Dict, axiom_id: str) -> bool:
        """
        验证数据是否符合axiom边界

        Args:
            data: BookGraph数据
            axiom_id: axiom ID

        Returns:
            bool: 是否符合边界
        """
        axiom = self.get_axiom(axiom_id)
        if not axiom:
            return True

        boundaries = axiom.get('boundaries', [])

        # ponytail: 简化验证逻辑（遍历boundaries检查字段）
        for boundary in boundaries:
            # 解析路径（如"chapters[*].core_argument"）
            if '*' in boundary:
                # 数组字段检查
                parts = boundary.split('[*].')
                array_field = parts[0]
                element_field = parts[1] if len(parts) > 1 else None

                array_data = data.get(array_field, [])
                if not isinstance(array_data, list):
                    continue

                for item in array_data:
                    if element_field and element_field in item:
                        # 执行self_check（简化版）
                        if self._execute_self_check(item[element_field], axiom):
                            return False
            else:
                # 单字段检查
                if boundary in data:
                    if self._execute_self_check(data[boundary], axiom):
                        return False

        return True

    def _execute_self_check(self, value: any, axiom: Dict) -> bool:
        """
        执行axiom的自检逻辑（简化版）

        Args:
            value: 字段值
            axiom: axiom定义

        Returns:
            bool: 是否违反规则
        """
        axiom_id = axiom.get('id')

        # ponytail: 根据axiom_id执行不同检查
        if axiom_id == 'no-placeholder-pollution':
            # 占位符检测
            placeholders = ['待补充', 'TBD', 'TODO', 'N/A', 'NULL']
            return any(ph in str(value) for ph in placeholders)

        elif axiom_id == 'no-empty-chapters':
            # 空洞章节检测
            return len(str(value)) < 50

        elif axiom_id == 'concept-definition-depth':
            # 概念定义深度检测
            return len(str(value)) < 30

        return False


class KDNAGenerationBoundary:
    """
    KDNA生成边界管理器

    加载@bookgraph/generation Truth Charter，确保生成流程符合判断边界
    """

    def __init__(self):
        """初始化生成边界管理器"""
        self.truth_charter = self._load_truth_charter()
        self.forbidden_simplifications = self.truth_charter.get('forbidden_simplifications', [])
        self.anti_drift_rules = self.truth_charter.get('anti_drift_rules', [])

    def _load_truth_charter(self) -> Dict:
        """加载Truth Charter"""
        charter_path = KDNA_ASSETS_PATH / "@bookgraph/generation/truth_charter.json"
        if charter_path.exists():
            return json.loads(charter_path.read_text(encoding='utf-8'))
        return {}

    def check_forbidden_simplification(self, content: str) -> bool:
        """
        检查内容是否包含禁止简化

        Args:
            content: 待检查内容

        Returns:
            bool: 是否包含禁止简化
        """
        for forbidden in self.forbidden_simplifications:
            if forbidden in content:
                return True
        return False

    def get_highest_question(self) -> str:
        """获取最高问题"""
        return self.truth_charter.get('highest_question', '')

    def get_core_insight(self) -> str:
        """获取核心洞见"""
        return self.truth_charter.get('core_insight', '')


class KDNAMetadataLoadPlan:
    """
    KDNA元数据增强LoadPlan执行器

    管理@bookgraph/metadata-enrichment的三层fallback链路
    """

    def __init__(self):
        """初始化LoadPlan执行器"""
        self.loadplan = self._load_loadplan()
        self.stages = self.loadplan.get('stages', [])

    def _load_loadplan(self) -> Dict:
        """加载LoadPlan"""
        loadplan_path = KDNA_ASSETS_PATH / "@bookgraph/metadata-enrichment/loadplan.json"
        if loadplan_path.exists():
            return json.loads(loadplan_path.read_text(encoding='utf-8'))
        return {}

    def get_stage(self, stage_id: str) -> Optional[Dict]:
        """
        获取指定stage

        Args:
            stage_id: stage ID（如'openlibrary_lookup'）

        Returns:
            Optional[Dict]: stage定义
        """
        for stage in self.stages:
            if stage.get('stage_id') == stage_id:
                return stage
        return None

    def get_fallback_chain(self) -> List[str]:
        """获取fallback链路"""
        return self.loadplan.get('fallback_chain', [])


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_kdna_quality_checker: Optional[KDNAQualityChecker] = None
_kdna_generation_boundary: Optional[KDNAGenerationBoundary] = None
_kdna_metadata_loadplan: Optional[KDNAMetadataLoadPlan] = None


def get_kdna_quality_checker() -> KDNAQualityChecker:
    """获取全局KDNA质量检查器单例"""
    global _kdna_quality_checker
    if _kdna_quality_checker is None:
        _kdna_quality_checker = KDNAQualityChecker()
    return _kdna_quality_checker


def get_kdna_generation_boundary() -> KDNAGenerationBoundary:
    """获取全局KDNA生成边界管理器单例"""
    global _kdna_generation_boundary
    if _kdna_generation_boundary is None:
        _kdna_generation_boundary = KDNAGenerationBoundary()
    return _kdna_generation_boundary


def get_kdna_metadata_loadplan() -> KDNAMetadataLoadPlan:
    """获取全局KDNA元数据LoadPlan执行器单例"""
    global _kdna_metadata_loadplan
    if _kdna_metadata_loadplan is None:
        _kdna_metadata_loadplan = KDNAMetadataLoadPlan()
    return _kdna_metadata_loadplan