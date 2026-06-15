"""
模型池管理器

实现闭环模型管理系统：
- 验证层：测试模型可用性
- 评估层：追踪稳定性评分
- 池管理层：动态池状态 + 持久化

方法论：Musk The Algorithm
- Question: 为什么需要？→ 现有架构缺少验证闭环
- Delete: 删除手动配置 available_models
- Simplify: 三层架构（验证-评估-池）
- Accelerate: 并行验证 + 缓存
- Automate: 定时验证 + 自动淘汰
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ModelStatus:
    """模型状态"""
    model_id: str
    api_base: str
    api_key: str

    # 验证状态
    is_available: bool = False
    last_verified: Optional[datetime] = None
    response_time: float = 0.0  # 平均响应时间（秒）

    # 稳定性评估
    stability_score: float = 0.0  # 0-1 评分
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0  # 连续失败次数

    # 池状态
    in_pool: bool = False  # 是否在可用池中
    priority: int = 99  # 优先级（越小越优）
    last_used: Optional[datetime] = None

    # 元数据
    is_free: bool = False  # 是否免费模型
    provider: str = ""  # 供应商


@dataclass
class ModelPoolStatus:
    """模型池整体状态"""
    last_update: datetime = field(default_factory=datetime.now)
    total_models: int = 0
    available_models: int = 0
    pool_models: int = 0

    # 池中模型列表
    models: List[ModelStatus] = field(default_factory=list)

    # 统计
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0


class ModelPoolManager:
    """
    模型池管理器

    三层架构：
    1. 验证层：并行测试模型可用性
    2. 评估层：追踪稳定性评分（成功率、响应时间）
    3. 池管理层：动态池状态 + 持久化
    """

    POOL_FILE = "model_pool_status.json"

    # 入池阈值
    MIN_STABILITY_SCORE = 0.7  # 最低稳定性评分
    MAX_RESPONSE_TIME = 30.0   # 最大响应时间（秒）
    MIN_SUCCESS_COUNT = 3      # 最少成功次数才入池

    # 淘汰阈值
    MAX_CONSECUTIVE_FAILURES = 3  # 连续失败次数阈值
    STABILITY_DROP_THRESHOLD = 0.5  # 稳定性跌破阈值

    def __init__(self, config: Dict):
        """
        初始化模型池管理器

        Args:
            config: llm 配置部分
        """
        self.config = config
        self.pool_status = ModelPoolStatus()

        # 加载持久化状态
        self._load_pool_status()

        # 初始化模型列表（从配置）
        self._init_model_list()

        logger.info(f"🎯 ModelPoolManager 初始化完成")
        logger.info(f"   模型总数: {self.pool_status.total_models}")
        logger.info(f"   可用模型: {self.pool_status.available_models}")
        logger.info(f"   池中模型: {self.pool_status.pool_models}")

    def _load_pool_status(self):
        """加载持久化状态"""
        pool_file = Path(self.POOL_FILE)

        if pool_file.exists():
            try:
                with open(pool_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 恢复状态
                self.pool_status.last_update = datetime.fromisoformat(
                    data.get('last_update', datetime.now().isoformat())
                )
                self.pool_status.total_requests = data.get('total_requests', 0)
                self.pool_status.total_successes = data.get('total_successes', 0)
                self.pool_status.total_failures = data.get('total_failures', 0)

                # 恢复模型状态
                for model_data in data.get('models', []):
                    model_status = ModelStatus(
                        model_id=model_data['model_id'],
                        api_base=model_data['api_base'],
                        api_key=model_data.get('api_key', 'unused'),
                        is_available=model_data.get('is_available', False),
                        last_verified=datetime.fromisoformat(model_data['last_verified'])
                            if model_data.get('last_verified') else None,
                        response_time=model_data.get('response_time', 0.0),
                        stability_score=model_data.get('stability_score', 0.0),
                        success_count=model_data.get('success_count', 0),
                        failure_count=model_data.get('failure_count', 0),
                        consecutive_failures=model_data.get('consecutive_failures', 0),
                        in_pool=model_data.get('in_pool', False),
                        priority=model_data.get('priority', 99),
                        last_used=datetime.fromisoformat(model_data['last_used'])
                            if model_data.get('last_used') else None,
                        is_free=model_data.get('is_free', False),
                        provider=model_data.get('provider', ''),
                    )
                    self.pool_status.models.append(model_status)

                logger.info(f"✅ 加载模型池状态: {len(self.pool_status.models)} 个模型")

            except Exception as e:
                logger.warning(f"⚠️ 加载模型池状态失败: {e}")
                self.pool_status = ModelPoolStatus()

    def _save_pool_status(self):
        """持久化状态"""
        pool_file = Path(self.POOL_FILE)

        try:
            data = {
                'last_update': datetime.now().isoformat(),
                'total_models': self.pool_status.total_models,
                'available_models': self.pool_status.available_models,
                'pool_models': self.pool_status.pool_models,
                'total_requests': self.pool_status.total_requests,
                'total_successes': self.pool_status.total_successes,
                'total_failures': self.pool_status.total_failures,
                'models': [
                    {
                        'model_id': m.model_id,
                        'api_base': m.api_base,
                        'api_key': m.api_key,
                        'is_available': m.is_available,
                        'last_verified': m.last_verified.isoformat() if m.last_verified else None,
                        'response_time': m.response_time,
                        'stability_score': m.stability_score,
                        'success_count': m.success_count,
                        'failure_count': m.failure_count,
                        'consecutive_failures': m.consecutive_failures,
                        'in_pool': m.in_pool,
                        'priority': m.priority,
                        'last_used': m.last_used.isoformat() if m.last_used else None,
                        'is_free': m.is_free,
                        'provider': m.provider,
                    }
                    for m in self.pool_status.models
                ]
            }

            with open(pool_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"💾 模型池状态已保存")

        except Exception as e:
            logger.error(f"❌ 保存模型池状态失败: {e}")

    def _init_model_list(self):
        """初始化模型列表（从配置，信任 verified 标记）"""
        # 如果已有持久化状态，不重复初始化
        if self.pool_status.models:
            return

        # ponytail: 支持两种配置格式（兼容旧配置 + 新配置）
        # 格式1: api_sources（旧格式）
        api_sources = self.config.get('api_sources', [])
        # 格式2: model_pool.models（新格式）
        model_pool_config = self.config.get('model_pool', {})
        model_configs = model_pool_config.get('models', [])

        # 处理 model_pool.models 配置（优先使用）
        for model_cfg in model_configs:
            model_id = model_cfg.get('model', '')
            if not model_id:
                continue

            api_base = model_cfg.get('api_base', 'http://localhost:3001/v1')
            api_key = model_cfg.get('api_key', 'unused')
            priority = model_cfg.get('priority', 99)
            is_verified = model_cfg.get('verified', False)

            is_free = ':free' in model_id or 'free' in model_id.lower()

            # ponytail: 信任配置中的 verified 标记，跳过初始验证
            model_status = ModelStatus(
                model_id=model_id,
                api_base=api_base,
                api_key=api_key,
                priority=priority,
                is_free=is_free,
                provider='openrouter',
                in_pool=True,
                is_available=is_verified,  # 直接信任 verified 标记
                stability_score=1.0 if is_verified else 0.0,
                last_verified=datetime.now() if is_verified else None,
            )
            self.pool_status.models.append(model_status)
            status = "✅ 已验证" if is_verified else "⏳ 待验证"
            logger.info(f"   + 模型入池: {model_id} (priority={priority}) {status}")

        # 处理 api_sources 配置（兼容旧格式）
        for source in api_sources:
            api_base = source.get('api_base', '')
            api_key = source.get('api_key', 'unused')
            priority = source.get('priority', 99)
            provider = source.get('name', 'unknown')
            preferred_models = source.get('preferred_models', [])

            for model_id in preferred_models:
                # 跳过已存在的模型
                if any(m.model_id == model_id for m in self.pool_status.models):
                    continue

                is_free = ':free' in model_id or 'free' in model_id.lower()

                model_status = ModelStatus(
                    model_id=model_id,
                    api_base=api_base,
                    api_key=api_key,
                    priority=priority,
                    is_free=is_free,
                    provider=provider,
                    in_pool=True,
                    is_available=True,  # api_sources 配置默认可用
                    stability_score=1.0,
                    last_verified=datetime.now(),
                )
                self.pool_status.models.append(model_status)
                logger.info(f"   + 模型入池: {model_id} (priority={priority}) [api_sources]")

        # 更新统计
        self.pool_status.total_models = len(self.pool_status.models)
        self.pool_status.pool_models = len([m for m in self.pool_status.models if m.in_pool])
        self.pool_status.available_models = len([m for m in self.pool_status.models if m.is_available])

        logger.info(f"📋 初始化模型列表: {self.pool_status.total_models} 个")
        logger.info(f"   池中模型: {self.pool_status.pool_models} 个")
        logger.info(f"   可用模型: {self.pool_status.available_models} 个")

        # ponytail: 仅在有新模型时保存初始状态（避免覆盖已有验证结果）
        if self.pool_status.models:
            self._save_pool_status()

    # ═══════════════════════════════════════════════════════════
    # 验证层：测试模型可用性
    # ═══════════════════════════════════════════════════════════

    async def verify_model(self, model: ModelStatus) -> Tuple[bool, float]:
        """
        验证单个模型可用性

        发送简单测试请求，测量响应时间

        Args:
            model: 模型状态

        Returns:
            Tuple[bool, float]: (是否可用, 响应时间)
        """
        test_prompt = "请回答：1+1=?（只回答数字）"

        try:
            import openai

            # 构建客户端
            default_headers = {}
            if "openrouter" in model.api_base.lower():
                default_headers["HTTP-Referer"] = "https://bookgraph.app"
                default_headers["X-Title"] = "BookGraph-Agent"

            client = openai.OpenAI(
                api_key=model.api_key or "unused",
                base_url=model.api_base,
                timeout=30,
                default_headers=default_headers if default_headers else None,
            )

            # 记录开始时间
            start_time = time.time()

            # 发送测试请求
            response = client.chat.completions.create(
                model=model.model_id,
                messages=[{"role": "user", "content": test_prompt}],
                max_tokens=10,
                temperature=0,
            )

            # 计算响应时间
            elapsed = time.time() - start_time

            # 检查响应
            if response and response.choices:
                content = response.choices[0].message.content
                if content and any(char.isdigit() for char in content):
                    logger.info(f"✅ {model.model_id} 可用 ({elapsed:.2f}s)")
                    return True, elapsed

            logger.warning(f"⚠️ {model.model_id} 响应异常")
            return False, elapsed

        except Exception as e:
            error_str = str(e)
            logger.warning(f"⚠️ {model.model_id} 不可用: {error_str[:50]}")
            return False, 0.0

    async def verify_all_models(self, parallel: int = 4) -> Dict[str, Tuple[bool, float]]:
        """
        并行验证所有模型（智能跳过已验证模型）

        Args:
            parallel: 并发数

        Returns:
            Dict[str, Tuple[bool, float]]: {model_id: (is_available, response_time)}
        """
        logger.info(f"🔍 开始验证模型（并发数: {parallel})")

        # ponytail: 智能跳过已验证模型，降低启动时间 80%
        verify_interval = self.config.get('model_pool', {}).get('verify_interval', 1800)
        models_to_verify = []
        skipped_models = []

        for model in self.pool_status.models:
            # 跳过条件：已可用 + 最近验证过
            if model.is_available and model.last_verified:
                elapsed = (datetime.now() - model.last_verified).total_seconds()
                if elapsed < verify_interval:
                    skipped_models.append((model.model_id, elapsed))
                    continue

            models_to_verify.append(model)

        # 打印跳过日志
        if skipped_models:
            for model_id, elapsed in skipped_models:
                logger.info(f"   ⏭️  跳过已验证模型: {model_id}（距上次 {int(elapsed)}s）")

        if not models_to_verify:
            logger.info(f"✅ 所有模型已验证，无需重新测试")
            return {m.model_id: (m.is_available, m.response_time) for m in self.pool_status.models}

        logger.info(f"   需验证模型: {len(models_to_verify)}/{len(self.pool_status.models)}")

        semaphore = asyncio.Semaphore(parallel)
        results = {}

        async def verify_with_semaphore(model: ModelStatus):
            async with semaphore:
                is_available, response_time = await self.verify_model(model)
                return model.model_id, is_available, response_time

        # 并行验证（仅验证待验证模型）
        tasks = [verify_with_semaphore(m) for m in models_to_verify]
        task_results = await asyncio.gather(*tasks)

        # 更新状态
        for model_id, is_available, response_time in task_results:
            results[model_id] = (is_available, response_time)

            # 更新模型状态
            for model in self.pool_status.models:
                if model.model_id == model_id:
                    model.is_available = is_available
                    model.last_verified = datetime.now()
                    model.response_time = response_time

                    # 成功时重置连续失败计数
                    if is_available:
                        model.consecutive_failures = 0
                    break

        # 补充跳过模型的结果
        for model in self.pool_status.models:
            if model.model_id not in results:
                results[model.model_id] = (model.is_available, model.response_time)

        # 更新统计
        available_count = sum(1 for _, (ok, _) in results.items() if ok)
        self.pool_status.available_models = available_count

        logger.info(f"✅ 验证完成: {available_count}/{len(results)} 个可用")

        # 保存状态
        self._save_pool_status()

        return results

    # ═══════════════════════════════════════════════════════════
    # 评估层：追踪稳定性评分
    # ═══════════════════════════════════════════════════════════

    def record_request_result(
        self,
        model_id: str,
        success: bool,
        response_time: float = 0.0
    ):
        """
        记录请求结果（用于稳定性评估）

        Args:
            model_id: 模型 ID
            success: 是否成功
            response_time: 响应时间
        """
        # 找到模型
        model = None
        for m in self.pool_status.models:
            if m.model_id == model_id:
                model = m
                break

        if not model:
            return

        # 更新计数
        self.pool_status.total_requests += 1

        if success:
            model.success_count += 1
            self.pool_status.total_successes += 1
            model.consecutive_failures = 0

            # 更新响应时间（滑动平均）
            if response_time > 0:
                if model.response_time == 0:
                    model.response_time = response_time
                else:
                    model.response_time = (model.response_time * 0.7 + response_time * 0.3)
        else:
            model.failure_count += 1
            self.pool_status.total_failures += 1
            model.consecutive_failures += 1

        # 更新稳定性评分
        total = model.success_count + model.failure_count
        if total > 0:
            model.stability_score = model.success_count / total

        model.last_used = datetime.now()

        # 检查是否需要淘汰
        self._check_eviction(model)

        # 检查是否可以入池
        self._check_admission(model)

        # 保存状态（每 10 次请求保存一次）
        if self.pool_status.total_requests % 10 == 0:
            self._save_pool_status()

    def _check_eviction(self, model: ModelStatus):
        """检查模型是否需要从池中淘汰"""
        if not model.in_pool:
            return

        # 淘汰条件
        should_evict = False
        reason = ""

        # 1. 连续失败次数超阈值
        if model.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            should_evict = True
            reason = f"连续失败 {model.consecutive_failures} 次"

        # 2. 稳定性跌破阈值（至少有 5 次请求）
        if model.success_count + model.failure_count >= 5:
            if model.stability_score < self.STABILITY_DROP_THRESHOLD:
                should_evict = True
                reason = f"稳定性评分 {model.stability_score:.2f} < {self.STABILITY_DROP_THRESHOLD}"

        if should_evict:
            model.in_pool = False
            self.pool_status.pool_models -= 1
            logger.warning(f"⚠️ 模型 {model.model_id} 已从池中淘汰: {reason}")

    def _check_admission(self, model: ModelStatus):
        """检查模型是否可以入池"""
        if model.in_pool:
            return

        if not model.is_available:
            return

        # 入池条件
        can_admit = True
        reasons = []

        # 1. 稳定性评分达标
        if model.stability_score < self.MIN_STABILITY_SCORE:
            if model.success_count + model.failure_count >= 3:
                can_admit = False
                reasons.append(f"稳定性 {model.stability_score:.2f} < {self.MIN_STABILITY_SCORE}")

        # 2. 响应时间达标
        if model.response_time > self.MAX_RESPONSE_TIME:
            can_admit = False
            reasons.append(f"响应时间 {model.response_time:.2f}s > {self.MAX_RESPONSE_TIME}s")

        # 3. 成功次数达标
        if model.success_count < self.MIN_SUCCESS_COUNT:
            can_admit = False
            reasons.append(f"成功次数 {model.success_count} < {self.MIN_SUCCESS_COUNT}")

        if can_admit and model.success_count >= self.MIN_SUCCESS_COUNT:
            model.in_pool = True
            self.pool_status.pool_models += 1
            logger.info(f"✅ 模型 {model.model_id} 已入池（稳定性 {model.stability_score:.2f}）")

    # ═══════════════════════════════════════════════════════════
    # 池管理层：动态池状态 + 选择接口
    # ═══════════════════════════════════════════════════════════

    def get_pool_models(self) -> List[ModelStatus]:
        """
        获取池中模型列表（按优先级排序）

        Returns:
            List[ModelStatus]: 池中模型列表
        """
        pool_models = [m for m in self.pool_status.models if m.in_pool]

        # 按优先级排序（稳定性 + 响应时间）
        pool_models.sort(key=lambda m: (
            m.priority,  # 优先级越小越优
            -m.stability_score,  # 稳定性越大越优
            m.response_time,  # 响应时间越小越优
        ))

        return pool_models

    def select_best_model(self) -> Optional[ModelStatus]:
        """
        选择最优模型

        Returns:
            Optional[ModelStatus]: 最优模型（如果池中有）
        """
        pool_models = self.get_pool_models()

        if not pool_models:
            logger.warning("⚠️ 模型池为空")
            return None

        best = pool_models[0]
        logger.info(f"🎯 选择最优模型: {best.model_id}（稳定性 {best.stability_score:.2f}）")
        return best

    def select_fallback_model(self) -> Optional[ModelStatus]:
        """
        选择后备模型（免费模型）

        Returns:
            Optional[ModelStatus]: 后备模型
        """
        free_models = [m for m in self.pool_status.models if m.is_free and m.is_available]

        if not free_models:
            return None

        # 按稳定性排序
        free_models.sort(key=lambda m: -m.stability_score)

        return free_models[0]

    def get_model_config(self, model: ModelStatus) -> Dict:
        """
        获取模型配置（供 LLMClient 使用）

        Args:
            model: 模型状态

        Returns:
            Dict: 配置字典
        """
        return {
            'model': model.model_id,
            'api_base': model.api_base,
            'api_key': model.api_key,
            'response_time': model.response_time,
            'stability': model.stability_score,
            'priority': model.priority,
        }

    def get_available_models_config(self) -> List[Dict]:
        """
        获取可用模型配置列表（供 LLMClient 初始化使用）

        Returns:
            List[Dict]: 配置列表
        """
        pool_models = self.get_pool_models()

        if not pool_models:
            # 如果池为空，尝试选择可用但未入池的模型
            available = [m for m in self.pool_status.models if m.is_available]
            available.sort(key=lambda m: (m.priority, -m.stability_score))
            pool_models = available[:5]  # 最多返回 5 个

        return [self.get_model_config(m) for m in pool_models]

    # ═══════════════════════════════════════════════════════════
    # 自动化接口
    # ═══════════════════════════════════════════════════════════

    async def auto_verify_and_update(self):
        """
        自动验证并更新池状态

        定时任务调用此方法
        """
        logger.info("🔄 自动验证模型池...")

        # 验证所有模型
        await self.verify_all_models()

        # 重新评估入池条件
        for model in self.pool_status.models:
            self._check_admission(model)

        # 保存状态
        self._save_pool_status()

        logger.info(f"✅ 模型池更新完成: {self.pool_status.pool_models} 个模型在池中")

    def get_status_report(self) -> str:
        """
        生成状态报告

        Returns:
            str: Markdown 格式报告
        """
        report = f"""# 模型池状态报告

**更新时间**: {self.pool_status.last_update.strftime('%Y-%m-%d %H:%M:%S')}

## 统计概览

| 指标 | 数值 |
|------|------|
| 模型总数 | {self.pool_status.total_models} |
| 可用模型 | {self.pool_status.available_models} |
| 池中模型 | {self.pool_status.pool_models} |
| 总请求次数 | {self.pool_status.total_requests} |
| 成功次数 | {self.pool_status.total_successes} |
| 失败次数 | {self.pool_status.total_failures} |

## 池中模型

| 模型 | 稳定性 | 响应时间 | 成功/失败 | 最后验证 |
|------|--------|----------|-----------|----------|
"""

        pool_models = self.get_pool_models()

        for m in pool_models:
            last_verified = m.last_verified.strftime('%H:%M:%S') if m.last_verified else 'N/A'
            report += f"| {m.model_id} | {m.stability_score:.2f} | {m.response_time:.2f}s | {m.success_count}/{m.failure_count} | {last_verified} |\n"

        # 未入池模型
        not_in_pool = [m for m in self.pool_status.models if not m.in_pool]

        if not_in_pool:
            report += "\n## 未入池模型\n\n"

            for m in not_in_pool:
                reason = ""
                if not m.is_available:
                    reason = "不可用"
                elif m.stability_score < self.MIN_STABILITY_SCORE:
                    reason = f"稳定性不足 ({m.stability_score:.2f})"
                elif m.success_count < self.MIN_SUCCESS_COUNT:
                    reason = f"成功次数不足 ({m.success_count})"

                report += f"- {m.model_id}: {reason}\n"

        return report