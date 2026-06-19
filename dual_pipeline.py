"""
双管线架构：解析线 + 修复线并行运行

线1（解析线）：持续解析新书，质量不达标仍落盘
线2（修复线）：监控修复清单，后台增量修复

两条线互不干扰，最大化吞吐量。
"""

import asyncio
import argparse
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import time

from utils.logger import setup_logger
from core.incremental_repair import IncrementalRepairSystem
from main import process_single_book_optimized, load_config
from core.book_graph_quality_checker import check_book_graph_quality

logger = setup_logger("DualPipeline")


class ParsePipeline:
    """解析线：持续解析新书"""

    def __init__(self, config: Dict, max_parallel: int = 4):
        self.config = config
        self.max_parallel = max_parallel
        self.processed_count = 0
        self.failed_count = 0
        self.repair_needed_count = 0

    async def process_batch(
        self,
        book_paths: List[Path],
        discipline: str = "哲学"
    ) -> Dict:
        """
        批量解析书籍（质量不达标仍落盘）

        Args:
            book_paths: 书籍路径列表
            discipline: 学科

        Returns:
            Dict: 处理统计
        """
        logger.info(f"📖 解析线启动：处理 {len(book_paths)} 本书")

        # 使用 semaphore 控制并发
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def process_with_semaphore(book_path):
            async with semaphore:
                try:
                    result = await process_single_book_optimized(
                        book_path,
                        self.config,
                        discipline,
                        self.max_parallel
                    )

                    if result.get('success'):
                        self.processed_count += 1

                        # 检查是否需要修复
                        if result.get('quality_passed') is False:
                            self.repair_needed_count += 1
                            logger.warning(f"   ⚠️ 需要修复: {book_path.name}")
                        else:
                            logger.info(f"   ✅ 质量达标: {book_path.name}")
                    else:
                        self.failed_count += 1
                        logger.error(f"   ❌ 解析失败: {book_path.name}")

                    return result

                except Exception as e:
                    self.failed_count += 1
                    logger.error(f"   ❌ 异常: {book_path.name} - {str(e)[:100]}")
                    return {'success': False, 'error': str(e)[:100]}

        # 并行处理所有书籍
        tasks = [process_with_semaphore(bp) for bp in book_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计
        logger.info(f"✅ 解析线完成：{self.processed_count}/{len(book_paths)} 成功")
        logger.info(f"   - 质量达标: {self.processed_count - self.repair_needed_count}")
        logger.info(f"   - 需要修复: {self.repair_needed_count}")
        logger.info(f"   - 解析失败: {self.failed_count}")

        return {
            'total': len(book_paths),
            'processed': self.processed_count,
            'repair_needed': self.repair_needed_count,
            'failed': self.failed_count,
            'results': results,
        }


class RepairPipeline:
    """修复线：监控并增量修复"""

    def __init__(
        self,
        config: Dict,
        repair_manifest_dir: Path,
        poll_interval: int = 60
    ):
        self.config = config
        self.repair_manifest_dir = Path(repair_manifest_dir)
        self.poll_interval = poll_interval
        self.repaired_count = 0

    async def run_continuous(self):
        """
        持续运行修复线（监控修复清单）
        """
        logger.info(f"🔧 修复线启动：监控 {self.repair_manifest_dir}")

        while True:
            try:
                # 扫描修复清单
                manifests = list(self.repair_manifest_dir.glob("*_repair_manifest.json"))

                if manifests:
                    logger.info(f"   📋 发现 {len(manifests)} 个待修复清单")

                    # 逐个修复
                    for manifest_path in manifests:
                        result = await self.repair_single(manifest_path)

                        if result.get('success'):
                            self.repaired_count += 1
                            logger.info(f"   ✅ 修复完成: {manifest_path.name}")
                        else:
                            logger.warning(f"   ⚠️ 修复失败: {manifest_path.name}")

                # 等待下一次扫描
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"   ❌ 修复线异常: {str(e)[:100]}")
                await asyncio.sleep(self.poll_interval)

    async def repair_single(self, manifest_path: Path) -> Dict:
        """
        修复单个书籍

        Args:
            manifest_path: 修复清单路径

        Returns:
            Dict: 修复结果
        """
        import json
        from batch_repair import repair_single_book

        try:
            # 加载修复清单
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            book_title = manifest.get('book_title', 'Unknown')
            logger.info(f"   🔧 开始修复: {book_title}")

            # 调用修复逻辑
            result = await repair_single_book(
                manifest_path,
                self.config,
                max_parallel=1
            )

            return result

        except Exception as e:
            logger.error(f"   ❌ 修复异常: {str(e)[:100]}")
            return {'success': False, 'error': str(e)[:100]}


async def run_dual_pipeline(
    book_paths: List[Path],
    config: Dict,
    discipline: str = "哲学",
    max_parse_parallel: int = 4,
    repair_poll_interval: int = 60
):
    """
    运行双管线：解析线 + 修复线

    Args:
        book_paths: 书籍路径列表
        config: 配置
        discipline: 学科
        max_parse_parallel: 解析线最大并行数
        repair_poll_interval: 修复线扫描间隔（秒）
    """
    logger.info(f"🚀 启动双管线架构")
    logger.info(f"   - 解析线：{len(book_paths)} 本书，{max_parse_parallel} 并行")
    logger.info(f"   - 修复线：每 {repair_poll_interval} 秒扫描一次")

    # 初始化两条线
    parse_pipeline = ParsePipeline(config, max_parse_parallel)
    repair_pipeline = RepairPipeline(
        config,
        Path(config.get('obsidian', {}).get('vault_path', '.')) / ".repair_manifests",
        repair_poll_interval
    )

    # 并行启动两条线
    parse_task = asyncio.create_task(
        parse_pipeline.process_batch(book_paths, discipline)
    )

    repair_task = asyncio.create_task(
        repair_pipeline.run_continuous()
    )

    # 等待解析线完成
    parse_result = await parse_task

    # 解析线完成后，等待修复线处理完所有清单
    logger.info(f"⏳ 解析线完成，等待修复线处理...")

    # 检查是否还有待修复清单
    max_wait_iterations = 20  # 最多等待20轮
    iteration = 0

    while iteration < max_wait_iterations:
        manifests = list(repair_pipeline.repair_manifest_dir.glob("*_repair_manifest.json"))

        if not manifests:
            logger.info(f"✅ 所有修复完成")
            break

        logger.info(f"   ⏳ 仍有 {len(manifests)} 个待修复清单...")
        await asyncio.sleep(repair_poll_interval)
        iteration += 1

    # 取消修复线任务
    repair_task.cancel()

    # 最终统计
    logger.info(f"📊 双管线完成统计：")
    logger.info(f"   - 解析成功: {parse_result['processed']}/{parse_result['total']}")
    logger.info(f"   - 需要修复: {parse_result['repair_needed']}")
    logger.info(f"   - 实际修复: {repair_pipeline.repaired_count}")
    logger.info(f"   - 解析失败: {parse_result['failed']}")

    return {
        'parse_result': parse_result,
        'repair_count': repair_pipeline.repaired_count,
    }


def main():
    parser = argparse.ArgumentParser(description="双管线架构：解析线 + 修复线")
    parser.add_argument("--input", required=True, help="书籍目录路径")
    parser.add_argument("--discipline", default="哲学", help="学科分类")
    parser.add_argument("--config", default="config.yaml", help="配置文件")
    parser.add_argument("--parse-parallel", type=int, default=4, help="解析线并行数")
    parser.add_argument("--repair-interval", type=int, default=60, help="修复线扫描间隔（秒）")

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 获取书籍路径
    input_path = Path(args.input)

    if input_path.is_dir():
        book_paths = (
            list(input_path.glob("*.epub")) +
            list(input_path.glob("*.pdf")) +
            list(input_path.glob("*.mobi"))
        )
    else:
        logger.error(f"输入路径不是目录: {input_path}")
        return

    if not book_paths:
        logger.error(f"未找到书籍文件: {input_path}")
        return

    # 过滤已解析的书籍
    output_dir = Path(config.get('obsidian', {}).get('vault_path', '.'))
    output_dir = output_dir / "📚 知识图谱" / args.discipline / "书籍图谱"

    if output_dir.exists():
        existing_files = set(
            f.stem for f in output_dir.glob("*.md")
            if not f.stem.startswith('_') and not f.stem.endswith('.mindmap')
        )

        book_paths = [
            bp for bp in book_paths
            if bp.stem not in existing_files
        ]

        logger.info(f"📖 过滤后剩余 {len(book_paths)} 本待解析")

    # 运行双管线
    asyncio.run(run_dual_pipeline(
        book_paths,
        config,
        args.discipline,
        args.parse_parallel,
        args.repair_interval
    ))


if __name__ == "__main__":
    main()
