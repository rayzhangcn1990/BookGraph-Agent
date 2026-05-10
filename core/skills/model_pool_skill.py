"""
模型池 Skill

提供模型池管理接口，作为 Skill 集成到 BookGraph。

功能：
1. 验证模型池（并行验证所有模型）
2. 生成状态报告
3. 提供模型选择接口给其他 Skill

注意：这不是内容生成 Skill，而是基础设施 Skill。
"""

import asyncio
import logging
from typing import Dict, List, Optional

from core.skills.base_skill import BaseSkill, SkillResult
from core.model_pool_manager import ModelPoolManager, ModelStatus

logger = logging.getLogger("BookGraph-Agent")


class ModelPoolSkill(BaseSkill):
    """
    模型池 Skill

    继承 BaseSkill 以统一接口，但功能是模型管理而非内容生成。
    """

    name = "model_pool"
    section_name = "model_pool_status"
    output_field = "pool_models"

    def __init__(self, config: Dict):
        """
        初始化模型池 Skill

        Args:
            config: llm 配置部分
        """
        super().__init__()

        self.pool_manager = ModelPoolManager(config)

    @property
    def prompt_template(self) -> str:
        """不使用提示词模板"""
        return ""

    def get_required_fields(self) -> List[str]:
        """不校验字段"""
        return []

    # ═══════════════════════════════════════════════════════════
    # 核心方法（覆盖基类）
    # ═══════════════════════════════════════════════════════════

    async def execute(
        self,
        llm_client,
        chunks: List[Dict],
        book_title: str,
        use_cache: bool = True
    ) -> Dict:
        """
        执行模型池验证

        Args:
            llm_client: LLM 客户端（不使用）
            chunks: 不使用
            book_title: 不使用
            use_cache: 是否使用缓存状态

        Returns:
            Dict: 模型池状态
        """
        import time
        start_time = time.time()

        # 如果使用缓存且池中有模型，直接返回
        if use_cache:
            pool_models = self.pool_manager.get_pool_models()
            if pool_models:
                logger.info(f"[{self.name}] 使用缓存池状态")
                return {
                    'pool_models': [self.pool_manager.get_model_config(m) for m in pool_models],
                    'from_cache': True,
                }

        # 并行验证所有模型
        await self.pool_manager.auto_verify_and_update()

        # 返回池状态
        pool_models = self.pool_manager.get_pool_models()

        elapsed = time.time() - start_time

        return {
            'pool_models': [self.pool_manager.get_model_config(m) for m in pool_models],
            'total_models': self.pool_manager.pool_status.total_models,
            'available_models': self.pool_manager.pool_status.available_models,
            'pool_models': self.pool_manager.pool_status.pool_models,
            'elapsed': elapsed,
            'from_cache': False,
        }

    def validate(self, result: Dict) -> tuple:
        """校验结果"""
        if not result:
            return False, ["结果为空"]

        if 'pool_models' not in result:
            return False, ["缺失 pool_models 字段"]

        if not result['pool_models']:
            return False, ["模型池为空"]

        return True, []

    def generate_markdown(
        self,
        result: Dict,
        extractions: List = None
    ) -> str:
        """
        生成 Markdown 状态报告

        Args:
            result: 执行结果
            extractions: 不使用

        Returns:
            str: Markdown 报告
        """
        return self.pool_manager.get_status_report()

    async def run_and_write(
        self,
        llm_client,
        chunks: List[Dict],
        book_title: str,
        obsidian_writer,
        discipline: str
    ) -> SkillResult:
        """
        执行验证并写入状态报告

        Args:
            llm_client: LLM 客户端（不使用）
            chunks: 不使用
            book_title: 不使用
            obsidian_writer: Obsidian 写入器
            discipline: 学科

        Returns:
            SkillResult: 执行结果
        """
        import time
        start_time = time.time()

        # 执行验证
        result = await self.execute(llm_client, chunks, book_title)

        # 校验
        is_valid, errors = self.validate(result)

        if not is_valid:
            logger.warning(f"⚠️ [{self.name}] 校验失败: {errors}")

        # 生成报告
        markdown = self.generate_markdown(result)

        # 写入（可选：写入到特定位置）
        # 目前只保存到文件，不写入 Obsidian

        elapsed = time.time() - start_time

        return SkillResult(
            skill_name=self.name,
            success=is_valid,
            result=result,
            errors=errors,
            elapsed_seconds=elapsed,
        )

    # ═══════════════════════════════════════════════════════════
    # 专用接口（供 LLMClient 使用）
    # ═══════════════════════════════════════════════════════════

    def get_available_models_config(self) -> List[Dict]:
        """
        获取可用模型配置（供 LLMClient 初始化）

        Returns:
            List[Dict]: 模型配置列表
        """
        return self.pool_manager.get_available_models_config()

    def select_best_model(self) -> Optional[ModelStatus]:
        """
        选择最优模型

        Returns:
            Optional[ModelStatus]: 最优模型
        """
        return self.pool_manager.select_best_model()

    def record_request_result(
        self,
        model_id: str,
        success: bool,
        response_time: float = 0.0
    ):
        """
        记录请求结果（供 LLMClient 反馈）

        Args:
            model_id: 模型 ID
            success: 是否成功
            response_time: 响应时间
        """
        self.pool_manager.record_request_result(model_id, success, response_time)

    async def verify_all_models(self) -> Dict:
        """
        并行验证所有模型

        Returns:
            Dict: 验证结果
        """
        return await self.pool_manager.verify_all_models()