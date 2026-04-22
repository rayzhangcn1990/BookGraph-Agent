#!/usr/bin/env python3
"""
BookGraph Agent - Hermes 工具调用版本

使用 Hermes 内置 LLM 处理书籍，无需外部 API Key。
"""

import sys
import json
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent))

from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from core.llm_client import CHUNK_ANALYSIS_PROMPT, SYSTEM_PROMPT, SYNTHESIS_PROMPT
from schemas.book_graph_schema import BookGraph, BookMetadata, TimeBackground, CriticalAnalysis, DisciplineType
from utils.logger import setup_logger

logger = setup_logger("BookGraph-Hermes")


def analyze_book_with_hermes(book_path: str, output_dir: str = None, discipline: str = "政治学", sub_discipline: str = None):
    """
    使用 Hermes 内置 LLM 分析书籍
    
    这个函数需要 Hermes Agent 通过工具调用来实现 LLM 调用。
    """
    logger.info("="*60)
    logger.info(f"📖 BookGraph Agent - Hermes 工具调用")
    logger.info("="*60)
    
    # Step 1: 解析书籍
    logger.info("\n📄 Step 1: 解析书籍...")
    parser = BookParser(book_path)
    result = parser.parse()
    
    if not result.success:
        logger.error(f"❌ 解析失败：{result.error}")
        return None
    
    book_title = result.metadata.get('title', Path(book_path).stem)
    book_author = result.metadata.get('author', 'Unknown')
    
    logger.info(f"✅ 解析成功")
    logger.info(f"   书名：{book_title}")
    logger.info(f"   作者：{book_author}")
    logger.info(f"   字符数：{len(result.content):,}")
    logger.info(f"   章节数：{len(result.chapters)}")
    
    # Step 2: 分块
    logger.info("\n🧩 Step 2: 分块处理...")
    full_content = "\n\n".join([ch["content"] for ch in result.chapters])
    chunk_size = 30000
    chunks = []
    for i in range(0, len(full_content), chunk_size):
        chunks.append(full_content[i:i+chunk_size])
    
    logger.info(f"   分块数：{len(chunks)}")
    
    # Step 3: 生成提示词 (供 Hermes 调用 LLM)
    logger.info("\n📝 Step 3: 生成 LLM 提示词...")
    
    prompts = []
    for i, chunk in enumerate(chunks):
        prompt = CHUNK_ANALYSIS_PROMPT.format(
            book_title=book_title,
            chunk_content=chunk[:25000],
        )
        prompts.append({
            "system": SYSTEM_PROMPT,
            "user": prompt,
            "chunk_index": i,
            "total_chunks": len(chunks)
        })
    
    logger.info(f"   提示词数量：{len(prompts)}")
    
    # Step 4: 输出提示词供 Hermes 调用
    print("\n" + "="*60)
    print("📋 Hermes LLM 调用提示词")
    print("="*60)
    print(f"\n需要调用 LLM {len(prompts)} 次，每次提示词：\n")
    
    for i, prompt_data in enumerate(prompts):
        print(f"--- 第 {i+1}/{len(prompts)} 块 ---")
        print(f"System: {prompt_data['system'][:200]}...")
        print(f"User: {prompt_data['user'][:500]}...")
        print()
    
    print("="*60)
    print("⚠️  以上是提示词预览，实际调用需要 Hermes Agent 执行")
    print("="*60)
    
    # Step 5: 创建测试用 BookGraph（演示）
    logger.info("\n📝 Step 5: 生成知识图谱（演示）...")
    
    test_graph = BookGraph(
        metadata=BookMetadata(
            title=book_title,
            author=book_author,
            author_intro='测试简介',
            discipline=DisciplineType(discipline) if discipline in [d.value for d in DisciplineType] else DisciplineType.哲学,
            category=['测试'],
            tags=['测试']
        ),
        time_background=TimeBackground(
            macro_background='测试宏观背景',
            micro_background='测试微观背景',
            core_contradiction='测试核心矛盾'
        ),
        critical_analysis=CriticalAnalysis(
            feminist_perspective='测试女性主义视角',
            postcolonial_perspective='测试后殖民主义视角',
            ethical_boundaries={}
        )
    )
    
    generator = GraphGenerator()
    markdown = generator.generate_book_graph_markdown(test_graph)
    
    # Step 6: 写入文件
    if output_dir:
        output_path = Path(output_dir) / f"{Path(book_path).stem}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        logger.info(f"✅ Markdown 已写入：{output_path}")
    
    logger.info("\n" + "="*60)
    logger.info("✅ 测试完成")
    logger.info("="*60)
    
    return {
        "book_title": book_title,
        "book_author": book_author,
        "content_length": len(result.content),
        "chunks_count": len(chunks),
        "prompts": prompts,
        "output_path": str(output_path) if output_dir else None
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="BookGraph Agent - Hermes 工具调用")
    parser.add_argument("--input", "-i", type=str, required=True, help="书籍文件路径")
    parser.add_argument("--output", "-o", type=str, default="/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治学/书籍图谱/", help="输出目录")
    parser.add_argument("--discipline", "-d", type=str, default="政治学", help="一级学科分类")
    parser.add_argument("--sub-discipline", "-s", type=str, default=None, help="二级子学科（如：政治哲学）")
    
    args = parser.parse_args()
    
    result = analyze_book_with_hermes(args.input, args.output, args.discipline)
    
    if result:
        print(f"\n✅ 处理完成！")
        print(f"   书名：{result['book_title']}")
        print(f"   作者：{result['book_author']}")
        print(f"   字符数：{result['content_length']:,}")
        print(f"   分块数：{result['chunks_count']}")
        if result['output_path']:
            print(f"   输出：{result['output_path']}")
