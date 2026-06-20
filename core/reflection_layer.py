"""
BookGraph-Agent 自我反思与调整机制

实现 Agent 的自我反思能力：
- 评估执行结果
- 识别改进机会
- 自动调整策略
- 多轮重试优化
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ReflectionResult:
    """反思结果"""
    passed: bool  # 是否通过
    quality_score: float  # 质量评分 0-1
    improvements: List[str]  # 改进建议
    retry_phase: Optional[str] = None  # 需要重试的阶段
    adjust_params: Optional[Dict] = None  # 需要调整的参数


class AgentReflector:
    """Agent 自我反思器"""

    def __init__(self, llm_client=None, config: Dict = None):
        """
        初始化反思器

        Args:
            llm_client: LLM 客户端（用于深度分析）
            config: 配置字典
        """
        self.llm_client = llm_client
        self.config = config or {}
        self.reflection_history: List[ReflectionResult] = []

    def evaluate_result(
        self,
        task_description: str,
        result: Dict,
        quality_score: float = None
    ) -> ReflectionResult:
        """
        评估执行结果

        Args:
            task_description: 任务描述
            result: 执行结果
            quality_score: 质量评分（可选，自动计算）

        Returns:
            ReflectionResult: 反思结果
        """
        # 计算质量评分
        if quality_score is None:
            quality_score = self._calculate_quality_score(result)

        # 基于规则快速评估
        improvements = []
        retry_phase = None
        adjust_params = {}

        # 检查占位符污染
        if self._has_placeholders(result):
            improvements.append("检测结果包含占位符（TBD/TODO/N/A），需重新生成")
            retry_phase = "synthesis"

        # 检查字段完整性
        missing_fields = self._check_required_fields(result)
        if missing_fields:
            improvements.append(f"缺失必填字段: {', '.join(missing_fields)}")
            adjust_params['enforce_required_fields'] = True

        # 检查内容空洞
        if self._has_empty_content(result):
            improvements.append("部分字段内容空洞，需要补充实质性内容")
            retry_phase = "process"

        # 检查章节完整性
        if self._check_chapter_integrity(result):
            improvements.append("章节数量不足或章节合并，需要拆分处理")

        # 决定是否通过
        passed = quality_score >= 0.6 and len(improvements) == 0

        reflection = ReflectionResult(
            passed=passed,
            quality_score=quality_score,
            improvements=improvements,
            retry_phase=retry_phase,
            adjust_params=adjust_params if adjust_params else None
        )

        # 记录反思历史
        self.reflection_history.append(reflection)

        logger.info(f"反思结果: {'通过' if passed else '未通过'} (质量分数: {quality_score:.2f})")
        if improvements:
            logger.warning(f"改进建议: {'; '.join(improvements)}")

        return reflection

    def deep_analyze(self, task_description: str, result: Dict) -> ReflectionResult:
        """
        深度分析（使用 LLM）

        Args:
            task_description: 任务描述
            result: 执行结果

        Returns:
            ReflectionResult: 反思结果
        """
        if not self.llm_client:
            logger.warning("LLM 客户端未初始化，回退到规则评估")
            return self.evaluate_result(task_description, result)

        try:
            prompt = f"""请评估以下任务执行结果的质量并提出改进建议。

【任务描述】
{task_description}

【执行结果】
{json.dumps(result, ensure_ascii=False, indent=2)[:2000]}

【评估要求】
1. 质量评分（0-1）：评估结果的完整性、准确性、可用性
2. 是否通过：质量分数 ≥ 0.6 且无明显问题
3. 改进建议：具体指出需要改进的地方
4. 重试阶段：如果需要重试，应从哪个阶段开始（parse/process/synthesis）
5. 参数调整：需要调整哪些参数

请以 JSON 格式输出：
{{
  "passed": true/false,
  "quality_score": 0.0-1.0,
  "improvements": ["建议1", "建议2"],
  "retry_phase": "阶段名或null",
  "adjust_params": {{"参数名": "值"}}
}}"""

            # 调用 LLM
            response = self.llm_client.call(prompt)
            analysis = json.loads(response)

            return ReflectionResult(
                passed=analysis.get('passed', False),
                quality_score=analysis.get('quality_score', 0.0),
                improvements=analysis.get('improvements', []),
                retry_phase=analysis.get('retry_phase'),
                adjust_params=analysis.get('adjust_params')
            )

        except Exception as e:
            logger.error(f"深度分析失败: {e}")
            return self.evaluate_result(task_description, result)

    def adjust_strategy(self, reflection: ReflectionResult, current_params: Dict) -> Dict:
        """
        根据反思结果调整策略

        Args:
            reflection: 反思结果
            current_params: 当前参数

        Returns:
            Dict: 调整后的参数
        """
        adjusted = current_params.copy()

        if not reflection.adjust_params:
            return adjusted

        # 应用参数调整
        for key, value in reflection.adjust_params.items():
            adjusted[key] = value
            logger.info(f"策略调整: {key} = {value}")

        # 根据历史反思调整权重
        if len(self.reflection_history) >= 3:
            # 最近 3 次都失败，降低并发度
            recent_failures = sum(1 for r in self.reflection_history[-3:] if not r.passed)
            if recent_failures >= 3:
                adjusted['max_parallel'] = max(1, current_params.get('max_parallel', 4) - 1)
                logger.warning(f"连续失败 {recent_failures} 次，降低并发度至 {adjusted['max_parallel']}")

        return adjusted

    def should_retry(self, reflection: ReflectionResult, retry_count: int, max_retries: int = 3) -> bool:
        """
        判断是否应该重试

        Args:
            reflection: 反思结果
            retry_count: 当前重试次数
            max_retries: 最大重试次数

        Returns:
            bool: 是否应该重试
        """
        if retry_count >= max_retries:
            logger.warning(f"已达到最大重试次数 {max_retries}，停止重试")
            return False

        # 质量分数过低，不重试
        if reflection.quality_score < 0.3:
            logger.warning(f"质量分数过低 ({reflection.quality_score:.2f})，不重试")
            return False

        # 有明确的改进建议和重试阶段，重试
        if reflection.retry_phase and reflection.improvements:
            logger.info(f"准备重试阶段: {reflection.retry_phase}")
            return True

        return False

    def _calculate_quality_score(self, result: Dict) -> float:
        """计算质量评分"""
        score = 0.0
        max_score = 5.0

        # 检查 1: 有核心字段
        if 'chapters' in result or 'chapter_summaries' in result:
            score += 1.0
        if 'core_concepts' in result:
            score += 1.0
        if 'key_insights' in result:
            score += 1.0

        # 检查 2: 内容有实质
        content_str = str(result)
        if len(content_str) > 500:
            score += 1.0

        # 检查 3: 无占位符
        if not self._has_placeholders(result):
            score += 1.0

        return score / max_score

    def _has_placeholders(self, result: Dict) -> bool:
        """检查是否有占位符"""
        result_str = str(result)
        import re
        return bool(re.search(r'TBD|TODO|N/A|待分析|待补充', result_str, re.IGNORECASE))

    def _check_required_fields(self, result: Dict) -> List[str]:
        """检查必填字段"""
        required_fields = ['chapters', 'core_concepts', 'key_insights']
        missing = []

        for field in required_fields:
            if field not in result or not result[field]:
                missing.append(field)

        return missing

    def _has_empty_content(self, result: Dict) -> bool:
        """检查是否有空洞内容"""
        for key, value in result.items():
            if isinstance(value, str) and len(value.strip()) < 20:
                return True
            if isinstance(value, list) and len(value) == 0:
                return True

        return False

    def _check_chapter_integrity(self, result: Dict) -> bool:
        """检查章节完整性"""
        chapters = result.get('chapters', [])
        if not chapters:
            return False

        # 检查是否有章节合并
        for chapter in chapters:
            if isinstance(chapter, dict):
                chapter_number = chapter.get('chapter_number', '')
                if '-' in str(chapter_number):  # 如 "11-22"
                    return True

        return False

    def get_learning_insights(self) -> List[str]:
        """获取学习洞察（基于历史反思）"""
        if len(self.reflection_history) < 5:
            return []

        insights = []

        # 统计常见问题
        common_improvements = {}
        for reflection in self.reflection_history:
            for improvement in reflection.improvements:
                key = improvement.split('，')[0]  # 提取关键词
                common_improvements[key] = common_improvements.get(key, 0) + 1

        # 识别高频问题
        for key, count in common_improvements.items():
            if count >= 3:
                insights.append(f"高频问题: {key}（出现 {count} 次），建议优化")

        # 识别成功率趋势
        recent_pass_rate = sum(1 for r in self.reflection_history[-5:] if r.passed) / 5
        if recent_pass_rate < 0.5:
            insights.append(f"最近 5 次通过率仅 {recent_pass_rate*100:.0f}%，建议检查配置")

        return insights


class AdaptiveRetryManager:
    """自适应重试管理器"""

    def __init__(self, reflector: AgentReflector):
        """
        初始化重试管理器

        Args:
            reflector: 反思器
        """
        self.reflector = reflector

    def execute_with_retry(
        self,
        task_func,
        task_description: str,
        initial_params: Dict,
        max_retries: int = 3
    ) -> Tuple[Dict, ReflectionResult]:
        """
        执行任务并自适应重试

        Args:
            task_func: 任务函数
            task_description: 任务描述
            initial_params: 初始参数
            max_retries: 最大重试次数

        Returns:
            Tuple[Dict, ReflectionResult]: (最终结果, 最终反思)
        """
        params = initial_params.copy()
        retry_count = 0
        last_result = None

        while retry_count < max_retries:
            try:
                # 执行任务
                result = task_func(**params)

                # 反思评估
                reflection = self.reflector.evaluate_result(task_description, result)

                # 通过则返回
                if reflection.passed:
                    logger.info(f"任务成功（重试 {retry_count} 次）")
                    return result, reflection

                # 判断是否重试
                if not self.reflector.should_retry(reflection, retry_count, max_retries):
                    return result, reflection

                # 调整策略
                params = self.reflector.adjust_strategy(reflection, params)
                retry_count += 1

                logger.warning(f"任务未通过，准备第 {retry_count + 1} 次尝试")

            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                retry_count += 1

                if retry_count >= max_retries:
                    raise

        # 返回最后一次结果
        return last_result or {}, reflection
