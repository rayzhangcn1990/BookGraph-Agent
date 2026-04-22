#!/usr/bin/env python3
"""
BookGraph Agent - Claude Code 工具调用版本

使用当前对话的 LLM（Claude Code）直接处理书籍分析，无需外部 API。

流程：
1. 解析书籍获取内容
2. 输出内容供 Claude Code 分析
3. Claude Code 直接生成知识图谱 JSON
4. 生成 Markdown 并写入 Obsidian
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from core.ocr_engine import OcrEngine
from schemas.book_graph_schema import BookGraph, BookMetadata, TimeBackground, CriticalAnalysis, ChapterSummary, CoreConcept, KeyInsight, KeyCase, KeyQuote, DisciplineType
from utils.logger import setup_logger

logger = setup_logger("BookGraph-Claude")


def parse_book(book_path: str, config: dict = None) -> dict:
    """
    解析书籍获取内容

    Returns:
        dict: 包含 metadata, content, chapters 的字典
    """
    logger.info(f"📖 解析书籍：{Path(book_path).name}")

    parser = BookParser(book_path, config or {})
    result = parser.parse()

    if not result.success:
        raise Exception(f"解析失败：{result.error}")

    # 如果是图片型 PDF，使用 OCR
    if result.is_image_based:
        logger.info("🔍 检测到图片型 PDF，启动 OCR...")
        ocr_engine = OcrEngine({'enabled': True, 'engine': 'paddleocr'})
        ocr_result = ocr_engine.process_pdf(book_path)
        if not ocr_result.get('success'):
            raise Exception(f"OCR 失败：{ocr_result.get('error')}")
        result.content = ocr_result['content']
        result.chapters = [{"chapter_id": "1", "title": "完整内容", "content": ocr_result['content']}]

    logger.info(f"✅ 解析完成：{len(result.content)}字符，{len(result.chapters)}章节")

    return {
        "metadata": result.metadata,
        "content": result.content,
        "chapters": result.chapters,
    }


def prepare_llm_prompt(book_data: dict) -> str:
    """
    准备供 Claude Code 分析的提示词

    Returns:
        str: 完整的提示词
    """
    book_title = book_data["metadata"].get('title', Path(book_data.get("path", "")).stem)
    book_author = book_data["metadata"].get('author', 'Unknown')

    # 合并章节内容
    full_content = "\n\n".join([ch["content"] for ch in book_data["chapters"]])

    # 截取主要内容（避免过长）
    max_content = 60000  # 约 60000 字符
    if len(full_content) > max_content:
        # 优先保留目录和前几章
        content_sample = full_content[:max_content]
    else:
        content_sample = full_content

    prompt = f"""请分析以下书籍内容，生成完整的知识图谱。

【书籍信息】
书名：{book_title}
作者：{book_author}

【书籍内容】
{content_sample}

【分析要求】
请生成完整的知识图谱 JSON，包含：

1. metadata（书籍元数据）
2. time_background（时代背景）
3. chapters（章节摘要数组，每章必须有实质内容）
4. core_concepts（核心概念数组，至少5个）
5. key_insights（关键洞见数组，至少3个）
6. key_cases（关键案例数组）
7. key_quotes（金句数组，至少5句）
8. critical_analysis（批判性分析）
9. learning_path（学习路径）
10. book_network（关联书籍网络）

【核心约束】
1. 严禁使用"待分析"、"待补充"等占位符
2. 所有内容必须有实质性信息
3. 底层逻辑必须使用三行格式：
   前提假设：[内容]
   推理链条：[内容]
   核心结论：[内容]
4. 章节标题必须是实际章节名，不是占位符

请以 JSON 格式输出完整的知识图谱。"""

    return prompt


def save_graph_to_obsidian(book_graph: BookGraph, output_dir: str) -> str:
    """
    生成 Markdown 并保存到 Obsidian

    Returns:
        str: 输出文件路径
    """
    generator = GraphGenerator()
    markdown = generator.generate_book_graph_markdown(book_graph)

    output_path = Path(output_dir) / f"{book_graph.metadata.title}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)

    logger.info(f"✅ 知识图谱已保存：{output_path}")
    return str(output_path)


def process_book_with_claude(book_path: str, discipline: str = "政治学", output_dir: str = None):
    """
    使用 Claude Code 处理书籍的完整流程

    这个函数会：
    1. 解析书籍
    2. 输出分析提示词
    3. 等待 Claude Code 提供分析结果（或接收外部提供的 JSON）
    4. 生成并保存知识图谱
    """
    logger.info("="*70)
    logger.info("📖 BookGraph Agent - Claude Code 工具调用模式")
    logger.info("="*70)

    # Step 1: 解析书籍
    book_data = parse_book(book_path)
    book_data["path"] = book_path

    book_title = book_data["metadata"].get('title', Path(book_path).stem)
    book_author = book_data["metadata"].get('author', 'Unknown')

    logger.info(f"   书名：{book_title}")
    logger.info(f"   作者：{book_author}")
    logger.info(f"   字符数：{len(book_data['content']):,}")
    logger.info(f"   章节数：{len(book_data['chapters'])}")

    # Step 2: 输出分析提示词
    prompt = prepare_llm_prompt(book_data)

    print("\n" + "="*70)
    print("📝 [Claude Code 分析请求]")
    print("="*70)
    print(f"书名：{book_title}")
    print(f"作者：{book_author}")
    print(f"内容长度：{len(book_data['content']):,} 字符")
    print("="*70)
    print("\n请 Claude Code 分析此书籍并生成知识图谱 JSON...\n")

    return {
        "book_title": book_title,
        "book_author": book_author,
        "prompt": prompt,
        "book_data": book_data,
        "discipline": discipline,
        "output_dir": output_dir or "/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治学/书籍图谱",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BookGraph Agent - Claude Code 工具调用")
    parser.add_argument("--input", "-i", type=str, required=True, help="书籍文件路径")
    parser.add_argument("--output", "-o", type=str, default="/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治学/书籍图谱", help="输出目录")
    parser.add_argument("--discipline", "-d", type=str, default="政治学", help="学科")

    args = parser.parse_args()

    result = process_book_with_claude(args.input, args.discipline, args.output)

    print(f"\n✅ 准备完成")
    print(f"   书名：{result['book_title']}")
    print(f"   提示词已生成，等待 Claude Code 分析...")