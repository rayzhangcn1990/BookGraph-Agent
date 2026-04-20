#!/usr/bin/env python3
"""
政治学书籍批量解析脚本
直接调用 LLM 处理书籍，生成 Obsidian 知识图谱
"""

import os
import sys
import json
import yaml
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.book_parser import BookParser
from core.obsidian_writer import ObsidianWriter
from core.ocr_engine import OcrEngine
from utils.logger import setup_logger

logger = setup_logger("PoliticsBatch")

# 配置
CONFIG = {
    'llm': {
        'max_tokens': 16384,
        'temperature': 0.3,
        'chunk_size': 30000,
    },
    'obsidian': {
        'vault_path': os.environ.get('OBSIDIAN_VAULT_PATH', '/Users/rayzhang/Documents/知识体系'),
        'graph_root': '📚 知识图谱',
    },
    'ocr': {
        'enabled': True,
        'engine': 'paddleocr',
    },
    'parsing': {
        'skip_scanned': False,
    },
}

# 学科映射
DISCIPLINE_MAP = {
    '政治学': '政治学',
    '政治哲学': '政治哲学',
}

def get_book_files(directory: str) -> list:
    """获取目录下所有书籍文件"""
    books_dir = Path(directory)
    book_files = []
    for f in books_dir.iterdir():
        if f.suffix.lower() in ['.pdf', '.epub', '.mobi']:
            book_files.append(f)
    return sorted(book_files)

def get_processed_books(graph_dir: str) -> set:
    """获取已处理的书籍名称"""
    processed = set()
    graph_path = Path(graph_dir)
    if graph_path.exists():
        for f in graph_path.iterdir():
            if f.suffix == '.md':
                processed.add(f.stem)
    return processed

def is_book_processed(book_name: str, processed_books: set) -> bool:
    """检查书籍是否已处理（模糊匹配）"""
    for processed in processed_books:
        # 简化匹配
        if book_name.split('：')[0] in processed or processed.split('：')[0] in book_name:
            return True
        if book_name.split(':')[0] in processed or processed.split(':')[0] in book_name:
            return True
    return False

def parse_book(book_path: Path, discipline: str = '政治学') -> dict:
    """解析单本书籍"""
    logger.info(f"📖 开始处理：{book_path.name}")
    
    try:
        # 解析书籍
        book_parser = BookParser(str(book_path), CONFIG.get('parsing', {}))
        parse_result = book_parser.parse()
        
        if not parse_result.success:
            logger.error(f"❌ 解析失败：{parse_result.error}")
            return {'success': False, 'error': parse_result.error}
        
        # 如果是图片型 PDF，使用 OCR
        if parse_result.is_image_based:
            logger.info("🔍 检测到图片型 PDF，启动 OCR 处理...")
            ocr_engine = OcrEngine(CONFIG.get('ocr', {}))
            ocr_result = ocr_engine.process_pdf(str(book_path))
            
            if not ocr_result.get('success'):
                logger.error(f"❌ OCR 失败：{ocr_result.get('error')}")
                return {'success': False, 'error': ocr_result.get('error')}
            
            parse_result.content = ocr_result['content']
            parse_result.chapters = [{
                "chapter_id": "1",
                "title": "完整内容",
                "content": ocr_result['content'],
            }]
        
        logger.info(f"✅ 解析完成：{len(parse_result.content)}字符，{len(parse_result.chapters)}章节")
        
        return {
            'success': True,
            'metadata': parse_result.metadata,
            'content': parse_result.content,
            'chapters': parse_result.chapters,
            'is_image_based': parse_result.is_image_based,
        }
        
    except Exception as e:
        logger.error(f"❌ 处理错误：{type(e).__name__}: {e}")
        return {'success': False, 'error': str(e)}

def main():
    books_dir = "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学"
    graph_dir = "/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治学/书籍图谱"
    
    print("=" * 70)
    print("          政治学书籍批量解析")
    print("=" * 70)
    print(f"书籍目录：{books_dir}")
    print(f"输出目录：{graph_dir}")
    print()
    
    # 获取书籍列表
    book_files = get_book_files(books_dir)
    print(f"📚 共有书籍：{len(book_files)} 本")
    
    # 获取已处理的书籍
    processed_books = get_processed_books(graph_dir)
    print(f"📝 已处理：{len(processed_books)} 本")
    
    # 找出未处理的书籍
    unprocessed = []
    for book_file in book_files:
        if not is_book_processed(book_file.stem, processed_books):
            unprocessed.append(book_file)
    
    print(f"⏳ 待处理：{len(unprocessed)} 本")
    print()
    
    if not unprocessed:
        print("✅ 所有书籍已处理完成！")
        return
    
    # 创建输出目录
    os.makedirs(graph_dir, exist_ok=True)
    
    # 处理每本书
    results = []
    for i, book_file in enumerate(unprocessed, 1):
        print(f"\n[{i}/{len(unprocessed)}] 处理：{book_file.name}")
        print("-" * 70)
        
        result = parse_book(book_file, '政治学')
        result['book_name'] = book_file.stem
        result['book_path'] = str(book_file)
        results.append(result)
        
        if result['success']:
            print(f"   ✅ 解析成功")
            print(f"   标题：{result['metadata'].get('title', 'N/A')}")
            print(f"   作者：{result['metadata'].get('author', 'N/A')}")
            print(f"   字符数：{len(result['content'])}")
        else:
            print(f"   ❌ 解析失败：{result.get('error', '未知错误')}")
    
    # 保存解析结果
    output_file = "/Users/rayzhang/BookGraph-Agent/politics_books_parsed.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print()
    print("=" * 70)
    print(f"✅ 解析完成！结果保存到：{output_file}")
    print(f"   成功：{sum(1 for r in results if r['success'])} 本")
    print(f"   失败：{sum(1 for r in results if not r['success'])} 本")
    print("=" * 70)
    
    # 输出待 LLM 处理的书籍列表
    print()
    print("📋 待 LLM 分析的书籍:")
    for r in results:
        if r['success']:
            print(f"   - {r['book_name']}")

if __name__ == '__main__':
    main()
