#!/usr/bin/env python3
"""
批量解析哲学书籍脚本

解析以下三个目录的书籍：
- 1-8.逻辑学
- 1-9.哲学入门
- 1-10.哲学专题

使用方法：
    python scripts/batch_parse_philosophy.py --workers 2
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


# 书籍目录配置
BOOK_DIRS = [
    {
        'name': '1-8.逻辑学',
        'path': '/Users/rayzhang/Documents/书/1.哲学/1-8.逻辑学',
        'discipline': '哲学',
        'sub_discipline': '逻辑学',
    },
    {
        'name': '1-9.哲学入门',
        'path': '/Users/rayzhang/Documents/书/1.哲学/1-9.哲学入门',
        'discipline': '哲学',
        'sub_discipline': '哲学入门',
    },
    {
        'name': '1-10.哲学专题',
        'path': '/Users/rayzhang/Documents/书/1.哲学/1-10.哲学专题',
        'discipline': '哲学',
        'sub_discipline': '哲学专题',
    },
]


async def process_book(
    book_path: Path,
    discipline: str,
    sub_discipline: str = None
) -> Dict:
    """
    处理单本书籍

    Args:
        book_path: 书籍路径
        discipline: 学科
        sub_discipline: 子学科

    Returns:
        Dict: 处理结果
    """
    from main import process_single_book_optimized, load_config

    logger.info(f"📖 开始处理: {book_path.name}")

    try:
        # 加载配置
        config = load_config("config.yaml")

        # 执行处理
        result = await process_single_book_optimized(
            book_path=book_path,
            config=config,
            discipline=discipline,
            max_parallel=4
        )

        if result.get('success'):
            logger.info(f"✅ 成功: {book_path.name}")
            return {
                'book_name': book_path.stem,
                'status': 'success',
                'output_path': result.get('output_path'),
                'elapsed': result.get('elapsed', 0),
            }
        else:
            error = result.get('error', '未知错误')
            logger.error(f"❌ 失败: {book_path.name} - {error}")
            return {
                'book_name': book_path.stem,
                'status': 'failed',
                'error': error,
            }

    except Exception as e:
        logger.error(f"❌ 异常: {book_path.name} - {e}")
        return {
            'book_name': book_path.stem,
            'status': 'failed',
            'error': str(e),
        }


async def process_directory(dir_config: Dict) -> Dict:
    """
    处理单个目录

    Args:
        dir_config: 目录配置

    Returns:
        Dict: 目录处理结果
    """
    dir_name = dir_config['name']
    dir_path = Path(dir_config['path'])
    discipline = dir_config['discipline']
    sub_discipline = dir_config.get('sub_discipline')

    logger.info(f"\n{'='*60}")
    logger.info(f"开始处理目录: {dir_name}")
    logger.info(f"{'='*60}")

    # 获取书籍文件列表
    book_files = list(dir_path.glob('*.epub')) + \
                 list(dir_path.glob('*.pdf')) + \
                 list(dir_path.glob('*.mobi')) + \
                 list(dir_path.glob('*.azw3'))

    logger.info(f"找到 {len(book_files)} 本书籍")

    results = []
    success_count = 0
    failed_count = 0

    for i, book_path in enumerate(book_files, 1):
        logger.info(f"\n[{i}/{len(book_files)}] {book_path.name}")

        result = await process_book(
            book_path=book_path,
            discipline=discipline,
            sub_discipline=sub_discipline
        )

        results.append(result)

        if result['status'] == 'success':
            success_count += 1
        else:
            failed_count += 1

    return {
        'dir_name': dir_name,
        'total': len(book_files),
        'success': success_count,
        'failed': failed_count,
        'results': results,
    }


async def main():
    """主函数"""
    print("=" * 60)
    print("批量解析哲学书籍")
    print("=" * 60)
    print()
    print(f"待处理目录: {len(BOOK_DIRS)} 个")
    for dir_config in BOOK_DIRS:
        print(f"  - {dir_config['name']}")
    print()

    all_results = []
    total_success = 0
    total_failed = 0
    start_time = datetime.now()

    # 逐目录处理
    for i, dir_config in enumerate(BOOK_DIRS, 1):
        print(f"\n[{i}/{len(BOOK_DIRS)}] 处理目录: {dir_config['name']}")

        dir_result = await process_directory(dir_config)
        all_results.append(dir_result)

        total_success += dir_result['success']
        total_failed += dir_result['failed']

        print(f"\n目录完成: {dir_result['success']}/{dir_result['total']} 成功")

    # 汇总结果
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("\n" + "=" * 60)
    print("批量解析完成")
    print("=" * 60)
    print(f"总计: {total_success + total_failed} 本")
    print(f"成功: {total_success} 本")
    print(f"失败: {total_failed} 本")
    print(f"耗时: {elapsed:.1f} 秒")
    print()

    # 保存结果
    output = {
        'timestamp': datetime.now().isoformat(),
        'elapsed_seconds': elapsed,
        'total_books': total_success + total_failed,
        'success_count': total_success,
        'failed_count': total_failed,
        'directories': all_results,
    }

    output_path = 'batch_parse_philosophy_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"结果已保存: {output_path}")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
