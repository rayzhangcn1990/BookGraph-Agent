#!/usr/bin/env python3
"""
修复章节缺失书籍脚本

针对检测到章节缺失问题的书籍，使用 --force 重新处理。

书籍清单：
- 世界哲学史（缺失第21章）
- 尼采·叔本华哲学经典合集（缺失第11-20章）
- Meditations/沉思录（缺失第13-20章）
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


# 需要修复的书籍配置
BOOKS_TO_REPAIR = [
    {
        'book_name': '世界哲学史',
        'source_file': '/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/世界哲学史.epub',
        'missing_chapters': ['21'],
        'discipline': '哲学',
    },
    {
        'book_name': '尼采·叔本华哲学经典合集',
        'source_file': '/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/尼采·叔本华哲学经典合集.epub',
        'missing_chapters': ['11', '12', '13', '14', '15', '16', '17', '18', '19', '20'],
        'discipline': '哲学',
    },
    {
        'book_name': 'Meditations',
        'source_file': '/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/沉思录.epub',
        'missing_chapters': ['13', '14', '15', '16', '17', '18', '19', '20'],
        'discipline': '哲学',
    },
]


async def repair_book(book_config: dict) -> dict:
    """
    修复单本书籍

    Args:
        book_config: 书籍配置

    Returns:
        dict: 修复结果
    """
    from main import process_single_book_optimized, load_config

    book_name = book_config['book_name']
    source_file = book_config['source_file']
    missing_chapters = book_config['missing_chapters']

    logger.info(f"开始修复: {book_name}")
    logger.info(f"  源文件: {source_file}")
    logger.info(f"  缺失章节: {missing_chapters}")

    # 检查文件是否存在
    if not os.path.exists(source_file):
        return {
            'book_name': book_name,
            'status': 'failed',
            'error': f'源文件不存在: {source_file}'
        }

    try:
        # 加载配置
        config = load_config("config.yaml")

        # 执行处理
        result = await process_single_book_optimized(
            book_path=Path(source_file),
            config=config,
            discipline=book_config.get('discipline', '哲学'),
            max_parallel=4
        )

        if result.get('success'):
            logger.info(f"✅ 修复成功: {book_name}")
            return {
                'book_name': book_name,
                'status': 'success',
                'output_path': result.get('output_path'),
            }
        else:
            logger.error(f"❌ 修复失败: {book_name} - {result.get('error')}")
            return {
                'book_name': book_name,
                'status': 'failed',
                'error': result.get('error'),
            }

    except Exception as e:
        logger.error(f"❌ 修复异常: {book_name} - {e}")
        return {
            'book_name': book_name,
            'status': 'failed',
            'error': str(e),
        }


async def main():
    """主函数"""
    results = []

    print("=" * 60)
    print("开始修复章节缺失书籍")
    print("=" * 60)
    print()

    for i, book_config in enumerate(BOOKS_TO_REPAIR, 1):
        print(f"[{i}/{len(BOOKS_TO_REPAIR)}] {book_config['book_name']}")
        print(f"  缺失章节: {', '.join(book_config['missing_chapters'])}")

        result = await repair_book(book_config)
        results.append(result)

        print()

    # 统计结果
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')

    print("=" * 60)
    print(f"修复完成: 成功 {success_count} 本, 失败 {failed_count} 本")
    print("=" * 60)

    # 保存结果
    output = {
        'timestamp': datetime.now().isoformat(),
        'total': len(results),
        'success': success_count,
        'failed': failed_count,
        'results': results,
    }

    with open('repair_chapter_missing_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: repair_chapter_missing_results.json")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
