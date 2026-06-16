"""
质量门控系统

整合到 Skill 执行流程中，实现：
1. Per-Skill 质量检查（立即检查，发现问题立即重试）
2. 质量分数阈值（低于80分自动回退）
3. 自动修复机制（最多重试3次）

方法论：Netflix Keeper Test + PUA Owner意识
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.book_graph_quality_checker import BookGraphQualityChecker, QualityCheckResult

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class QualityGateConfig:
    """质量门控配置"""
    enabled: bool = True
    threshold: float = 80.0
    auto_retry: bool = True
    max_retries: int = 3


class QualityGateError(Exception):
    """质量门控错误"""
    def __init__(self, quality_score: float, issues: List[str]):
        self.quality_score = quality_score
        self.issues = issues
        super().__init__(
            f"质量分数未达标: {quality_score}（阈值: 80.0）\n"
            f"问题列表:\n{chr(10).join(f'- {issue}' for issue in issues)}"
        )


class QualityGate:
    """
    质量门控系统

    使用方法：
    ```python
    from core.quality_gate import QualityGate

    gate = QualityGate(config)
    result = await gate.execute_with_quality_check(skill)
    ```

    核心流程：
    1. 执行Skill
    2. 立即检查质量
    3. 如果不达标，自动重试（最多3次）
    4. 如果仍不达标，抛出QualityGateError
    """

    def __init__(self, config: QualityGateConfig):
        """
        初始化质量门控

        Args:
            config: 质量门控配置
        """
        self.config = config
        self.checker = BookGraphQualityChecker()

    def check_quality(self, data: Dict) -> QualityCheckResult:
        """
        检查数据质量

        Args:
            data: 待检查的数据（BookGraph或Chunk结果）

        Returns:
            QualityCheckResult: 质量检查结果
        """
        # 🗝️ 修复：调用正确的check方法签名
        # BookGraphQualityChecker.check() 接受 book_graph_data 和可选的 expected_chapters
        return self.checker.check(data, expected_chapters=0)

    def should_retry(self, quality: QualityCheckResult) -> bool:
        """
        判断是否需要重试

        Args:
            quality: 质量检查结果

        Returns:
            bool: 是否需要重试
        """
        return (
            self.config.enabled
            and self.config.auto_retry
            and quality.score < self.config.threshold
            and quality.passed == False
        )

    def execute_with_quality_gate(
        self,
        execute_func: callable,
        validate_func: Optional[callable] = None,
        skill_name: str = "Unknown"
    ) -> Dict:
        """
        执行任务并通过质量门控

        Args:
            execute_func: 执行函数（返回数据）
            validate_func: 验证函数（可选，用于验证数据有效性）
            skill_name: Skill名称（用于日志）

        Returns:
            Dict: 执行结果（通过质量检查）

        Raises:
            QualityGateError: 质量分数未达标
        """
        result = None
        quality = None

        # 首次执行
        result = execute_func()

        # 验证数据有效性（可选）
        if validate_func and not validate_func(result):
            logger.warning(f"{skill_name}: 数据验证失败，将触发重试")
            quality = QualityCheckResult(
                passed=False,
                score=0.0,
                issues=["数据验证失败"],
                warnings=[],
                stats={}
            )
        else:
            # 检查质量
            quality = self.check_quality(result)

        logger.info(
            f"{skill_name} 质量检查: "
            f"分数={quality.score:.1f}, "
            f"通过={quality.passed}, "
            f"问题数={len(quality.issues)}"
        )

        # 如果不达标，自动重试
        if self.should_retry(quality):
            retry_count = 0
            while retry_count < self.config.max_retries:
                retry_count += 1

                logger.warning(
                    f"{skill_name}: 质量分数 {quality.score:.1f} "
                    f"未达标（阈值 {self.config.threshold}），"
                    f"第 {retry_count}/{self.config.max_retries} 次重试"
                )

                # 重试执行
                result = execute_func()

                # 验证数据有效性（可选）
                if validate_func and not validate_func(result):
                    logger.warning(f"{skill_name}: 数据验证失败（重试 {retry_count}）")
                    quality = QualityCheckResult(
                        passed=False,
                        score=0.0,
                        issues=["数据验证失败"],
                        warnings=[],
                        stats={}
                    )
                else:
                    # 重新检查质量
                    quality = self.check_quality(result)

                logger.info(
                    f"{skill_name} 重试 {retry_count} 质量检查: "
                    f"分数={quality.score:.1f}, "
                    f"通过={quality.passed}"
                )

                # 如果达标，退出重试循环
                if quality.score >= self.config.threshold:
                    logger.info(
                        f"{skill_name}: 重试成功，质量分数 "
                        f"{quality.score:.1f} >= {self.config.threshold}"
                    )
                    break

            # 如果仍不达标，抛出错误
            if quality.score < self.config.threshold:
                logger.error(
                    f"{skill_name}: 重试 {retry_count} 次后仍不达标，"
                    f"质量分数 {quality.score:.1f}"
                )
                raise QualityGateError(quality.score, quality.issues)

        return result

    def get_quality_report(self, quality: QualityCheckResult) -> str:
        """
        生成质量报告

        Args:
            quality: 质量检查结果

        Returns:
            str: 质量报告（Markdown格式）
        """
        report = f"""
## 质量检查报告

**分数**: {quality.score:.1f}/100
**通过**: {quality.passed}

### 统计信息
{chr(10).join(f'- {k}: {v}' for k, v in quality.stats.items())}

### 问题列表 ({len(quality.issues)}项)
{chr(10).join(f'- {issue}' for issue in quality.issues)}

### 警告列表 ({len(quality.warnings)}项)
{chr(10).join(f'- {warning}' for warning in quality.warnings)}
"""
        return report


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_gate: Optional[QualityGate] = None


def get_quality_gate(config_dict: Optional[Dict] = None) -> QualityGate:
    """
    获取质量门控单例

    Args:
        config_dict: 配置字典（可选）

    Returns:
        QualityGate: 质量门控实例
    """
    global _gate

    if _gate is None:
        config = QualityGateConfig(
            enabled=config_dict.get("enabled", True) if config_dict else True,
            threshold=config_dict.get("threshold", 80.0) if config_dict else 80.0,
            auto_retry=config_dict.get("auto_retry", True) if config_dict else True,
            max_retries=config_dict.get("max_retries", 3) if config_dict else 3
        )
        _gate = QualityGate(config)

    return _gate


def check_data_quality(data: Dict) -> QualityCheckResult:
    """
    检查数据质量的便捷函数

    Args:
        data: 待检查的数据

    Returns:
        QualityCheckResult: 质量检查结果
    """
    gate = get_quality_gate()
    return gate.check_quality(data)


def execute_with_quality_check(
    execute_func: callable,
    validate_func: Optional[callable] = None,
    skill_name: str = "Unknown"
) -> Dict:
    """
    执行任务并通过质量检查的便捷函数

    Args:
        execute_func: 执行函数
        validate_func: 验证函数（可选）
        skill_name: Skill名称

    Returns:
        Dict: 执行结果
    """
    gate = get_quality_gate()
    return gate.execute_with_quality_gate(execute_func, validate_func, skill_name)