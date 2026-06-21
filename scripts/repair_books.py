#!/usr/bin/env python3
"""
批量修复低分书籍脚本

根据质量检查结果，重新处理低分书籍，生成高质量知识图谱。

使用方法：
    python scripts/repair_books.py --input matched_books.json --workers 2
    python scripts/repair_books.py --input matched_books.json --dry-run
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


def repair_single_book(
    book_path: str,
    discipline: str = None,
    force: bool = True,
    dry_run: bool = False
) -> Dict:
    """
    修复单本书籍

    Args:
        book_path: 书籍文件路径
        discipline: 学科分类
        force: 是否强制重新处理
        dry_run: 是否为模拟运行

    Returns:
        Dict: 修复结果
    """
    import asyncio
    from pathlib import Path as PathLib
    from main import process_single_book_optimized, load_config

    logger.info(f"开始处理书籍: {book_path}")

    if dry_run:
        return {
            "status": "dry_run",
            "book_path": book_path,
            "message": "模拟运行，未实际处理"
        }

    try:
        # 加载配置
        config = load_config("config.yaml")

        # 调用主处理流程
        # 注意：参数名是 book_path 而不是 input_path
        result = asyncio.run(
            process_single_book_optimized(
                book_path=PathLib(book_path),
                config=config,
                discipline=discipline or "哲学",
                max_parallel=4
            )
        )

        return {
            "status": "success" if result.get("success") else "failed",
            "book_path": book_path,
            "result": result
        }

    except Exception as e:
        logger.error(f"处理书籍失败: {book_path}, 错误: {e}")
        return {
            "status": "failed",
            "book_path": book_path,
            "error": str(e)
        }


def batch_repair_books(
    matched_books: List[Dict],
    workers: int = 2,
    dry_run: bool = False,
    stop_on_error: bool = False
) -> Dict:
    """
    批量修复书籍

    Args:
        matched_books: 匹配的书籍列表
        workers: 并发数
        dry_run: 是否为模拟运行
        stop_on_error: 是否在出错时停止

    Returns:
        Dict: 批量处理结果
    """
    results = {
        "total": len(matched_books),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
        "start_time": datetime.now().isoformat(),
    }

    for idx, book in enumerate(matched_books, 1):
        book_name = book.get("book_name", "Unknown")
        book_path = book.get("path")

        logger.info(f"[{idx}/{len(matched_books)}] 处理书籍: {book_name}")

        if not book_path or not os.path.exists(book_path):
            logger.warning(f"书籍文件不存在: {book_path}")
            results["skipped"] += 1
            results["details"].append({
                "book_name": book_name,
                "status": "skipped",
                "reason": "文件不存在"
            })
            continue

        # 执行修复
        result = repair_single_book(
            book_path=book_path,
            discipline="哲学",  # 默认哲学
            force=True,
            dry_run=dry_run
        )

        results["details"].append({
            "book_name": book_name,
            "book_path": book_path,
            **result
        })

        if result["status"] == "success":
            results["success"] += 1
        elif result["status"] == "failed":
            results["failed"] += 1
            if stop_on_error:
                logger.error(f"处理失败，停止后续处理")
                break

    results["end_time"] = datetime.now().isoformat()

    return results


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量修复低分书籍')

    parser.add_argument(
        '--input',
        type=str,
        default='matched_books.json',
        help='匹配书籍列表（JSON格式）'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='并发数（当前仅支持串行）'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='模拟运行，不实际处理'
    )

    parser.add_argument(
        '--stop-on-error',
        action='store_true',
        help='出错时停止'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='repair_results.json',
        help='修复结果输出路径'
    )

    args = parser.parse_args()

    # 加载匹配书籍列表
    with open(args.input, 'r', encoding='utf-8') as f:
        matched_books = json.load(f)

    logger.info(f"加载 {len(matched_books)} 本待修复书籍")

    # 执行批量修复
    results = batch_repair_books(
        matched_books=matched_books,
        workers=args.workers,
        dry_run=args.dry_run,
        stop_on_error=args.stop_on_error
    )

    # 保存结果
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"修复结果已保存: {args.output}")

    # 打印摘要
    print(f"\n修复完成:")
    print(f"  总计: {results['total']} 本")
    print(f"  成功: {results['success']} 本")
    print(f"  失败: {results['failed']} 本")
    print(f"  跳过: {results['skipped']} 本")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    main()
