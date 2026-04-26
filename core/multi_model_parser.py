"""
多模型并行解析器
- 同时使用多个模型解析多本书
- 自动分配任务到不同模型
- 支持并行处理和进度监控
"""

import asyncio
import logging
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import json

import httpx

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class ModelTask:
    model_id: str
    book_path: str
    status: str  # pending, running, completed, failed
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


class MultiModelParallelParser:
    """多模型并行解析器"""

    # 高性能模型列表（用于并行处理）
    HIGH_PERFORMANCE_MODELS = [
        "claude-opus-4.7",
        "claude-sonnet-4.6",
        "deepseek-r1",
        "gemini-2.5-pro",
    ]

    # 快速模型列表（用于简单任务）
    FAST_MODELS = [
        "claude-haiku-4.5",
        "gemini-2.5-flash",
        "deepseek-v3",
        "gpt-4o",
    ]

    def __init__(self, api_base: str, api_key: str = "unused", max_parallel: int = 3):
        """
        Args:
            api_base: API地址
            api_key: API密钥
            max_parallel: 最大并行数
        """
        self.api_base = api_base
        self.api_key = api_key
        self.max_parallel = max_parallel
        self.available_models: List[str] = []
        self.task_queue: List[ModelTask] = []
        self.running_tasks: Dict[str, asyncio.Task] = {}

    async def fetch_available_models(self) -> List[str]:
        """获取可用模型列表"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.api_base}/v1/models",
                    headers={"x-api-key": self.api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m['id'] for m in data.get('data', [])]
                    self.available_models = models
                    logger.info(f"✅ 获取到 {len(models)} 个可用模型")
                    return models
                return []
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []

    def select_model_for_task(self, task_type: str = "heavy") -> Optional[str]:
        """
        根据任务类型选择模型

        Args:
            task_type: heavy (大书) / light (小书) / synthesis (综合)
        """
        available = self.available_models

        if task_type == "heavy":
            # 大书需要强推理能力
            for model in self.HIGH_PERFORMANCE_MODELS:
                if model in available:
                    return model
        elif task_type == "light":
            # 小书可以用快速模型
            for model in self.FAST_MODELS:
                if model in available:
                    return model
        else:
            # 综合任务需要强推理
            for model in self.HIGH_PERFORMANCE_MODELS:
                if model in available:
                    return model

        # 后备：返回第一个可用模型
        return available[0] if available else None

    async def parse_book_with_model(
        self,
        book_path: str,
        model: str,
        discipline: str,
        output_dir: str
    ) -> ModelTask:
        """使用指定模型解析单本书"""
        task = ModelTask(
            model_id=model,
            book_path=book_path,
            status="running",
            start_time=datetime.now()
        )

        try:
            # 导入主解析函数
            from main import process_single_book
            import yaml

            # 加载完整配置
            config_path = Path(__file__).parent.parent / "config.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f)

            # 修改 llm 配置使用指定模型
            if "llm" not in config:
                config["llm"] = {}
            config["llm"]["model"] = model
            config["llm"]["api_base"] = self.api_base
            config["llm"]["api_key"] = self.api_key

            # 执行解析（使用 asyncio 包装）
            result = await asyncio.to_thread(
                process_single_book,
                Path(book_path),
                config,
                discipline
            )

            task.status = "completed"
            task.end_time = datetime.now()
            task.output_path = result.get("output_path", "")

            logger.info(f"✅ [{model}] 完成: {Path(book_path).name}")

        except Exception as e:
            task.status = "failed"
            task.end_time = datetime.now()
            task.error = str(e)
            logger.error(f"❌ [{model}] 失败: {Path(book_path).name} - {e}")

        return task

    async def parse_books_parallel(
        self,
        book_paths: List[str],
        discipline: str,
        output_dir: str
    ) -> List[ModelTask]:
        """
        并行解析多本书

        Args:
            book_paths: 书籍路径列表
            discipline: 学科
            output_dir: 输出目录

        Returns:
            List[ModelTask]: 任务结果列表
        """
        # 获取可用模型
        await self.fetch_available_models()

        if not self.available_models:
            logger.error("没有可用模型")
            return []

        # 选择高性能模型用于并行处理
        primary_models = [
            m for m in self.HIGH_PERFORMANCE_MODELS
            if m in self.available_models
        ]

        if not primary_models:
            primary_models = self.available_models[:self.max_parallel]

        # 创建任务队列
        tasks = []
        for i, book_path in enumerate(book_paths):
            # 轮询分配模型
            model = primary_models[i % len(primary_models)]
            tasks.append(ModelTask(
                model_id=model,
                book_path=book_path,
                status="pending"
            ))

        # 并行执行
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def run_task_with_semaphore(task: ModelTask):
            async with semaphore:
                task.status = "running"
                task.start_time = datetime.now()
                result = await self.parse_book_with_model(
                    task.book_path,
                    task.model_id,
                    discipline,
                    output_dir
                )
                return result

        # 启动所有任务
        results = await asyncio.gather(
            *[run_task_with_semaphore(t) for t in tasks],
            return_exceptions=True
        )

        # 处理结果
        final_tasks = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_tasks.append(ModelTask(
                    model_id=tasks[i].model_id,
                    book_path=tasks[i].book_path,
                    status="failed",
                    error=str(result)
                ))
            else:
                final_tasks.append(result)

        return final_tasks

    def print_summary(self, tasks: List[ModelTask]):
        """打印任务摘要"""
        completed = [t for t in tasks if t.status == "completed"]
        failed = [t for t in tasks if t.status == "failed"]

        print("\n" + "=" * 60)
        print("📊 解析任务摘要")
        print("=" * 60)
        print(f"✅ 完成: {len(completed)} 本")
        print(f"❌ 失败: {len(failed)} 本")

        if completed:
            print("\n已完成的书籍:")
            for t in completed:
                duration = (t.end_time - t.start_time).total_seconds()
                print(f"  - [{t.model_id}] {Path(t.book_path).name} ({duration:.1f}s)")

        if failed:
            print("\n失败的书籍:")
            for t in failed:
                print(f"  - [{t.model_id}] {Path(t.book_path).name}: {t.error}")

        print("=" * 60)


async def batch_parse_with_multi_models(
    book_paths: List[str],
    discipline: str,
    api_base: str = "http://localhost:18765",
    api_key: str = "unused",
    max_parallel: int = 3
):
    """
    使用多模型并行解析多本书

    使用示例:
        book_paths = [
            "/path/to/book1.epub",
            "/path/to/book2.epub",
        ]
        await batch_parse_with_multi_models(book_paths, "政治学", max_parallel=3)
    """
    parser = MultiModelParallelParser(api_base, api_key, max_parallel)
    output_dir = Path.home() / "Documents" / "知识体系" / "📚 知识图谱" / discipline / "书籍图谱"

    tasks = await parser.parse_books_parallel(book_paths, discipline, str(output_dir))
    parser.print_summary(tasks)

    return tasks


if __name__ == "__main__":
    # 测试示例
    import sys

    books = sys.argv[1:] if len(sys.argv) > 1 else []
    if books:
        asyncio.run(batch_parse_with_multi_models(books, "政治学"))