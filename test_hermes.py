#!/usr/bin/env python3
"""
BookGraph Agent - Hermes LLM 测试脚本

使用 Hermes 内置 LLM 测试书籍解析功能。
"""

import sys
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from utils.logger import setup_logger

logger = setup_logger("BookGraph-Test")


def test_parse_book(book_path: str):
    """测试书籍解析"""
    logger.info(f"📖 测试解析：{book_path}")
    
    parser = BookParser(book_path)
    result = parser.parse()
    
    if result.success:
        logger.info(f"✅ 解析成功")
        logger.info(f"   字符数：{len(result.content)}")
        logger.info(f"   章节数：{len(result.chapters)}")
        logger.info(f"   书名：{result.metadata.get('title', 'Unknown')}")
        logger.info(f"   作者：{result.metadata.get('author', 'Unknown')}")
        return result
    else:
        logger.error(f"❌ 解析失败：{result.error}")
        return None


def test_generate_prompt(parse_result, book_title: str):
    """生成 LLM 提示词"""
    from core.llm_client import CHUNK_ANALYSIS_PROMPT, SYSTEM_PROMPT
    
    # 准备内容块
    full_content = "\n\n".join([ch["content"] for ch in parse_result.chapters])
    
    # 分块（每块 30000 字符）
    chunk_size = 30000
    chunks = []
    for i in range(0, len(full_content), chunk_size):
        chunks.append(full_content[i:i+chunk_size])
    
    logger.info(f"📝 生成 {len(chunks)} 个分析块")
    
    prompts = []
    for i, chunk in enumerate(chunks):
        prompt = CHUNK_ANALYSIS_PROMPT.format(
            book_title=book_title,
            chunk_content=chunk[:25000],  # 限制长度
        )
        prompts.append({
            "system": SYSTEM_PROMPT,
            "user": prompt,
            "chunk_index": i,
            "total_chunks": len(chunks)
        })
    
    return prompts


def test_hermes_llm_call(system_prompt: str, user_prompt: str) -> str:
    """
    调用 Hermes LLM
    
    这个函数需要 Hermes Agent 通过工具调用来实现。
    以下是伪代码示例：
    
    在 Hermes Agent 中执行:
    ```python
    from core.llm_client import LLMClient
    
    client = LLMClient({'provider': 'dashscope', 'model': 'qwen3.5-plus'})
    response = client._call_llm([
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt}
    ])
    ```
    """
    print(f"\n{'='*60}")
    print(f"📝 [Hermes LLM 调用]")
    print(f"{'='*60}")
    print(f"系统提示（前 200 字符）：{system_prompt[:200]}...")
    print(f"用户输入（前 200 字符）：{user_prompt[:200]}...")
    print(f"{'='*60}")
    print(f"⚠️  此步骤需要 Hermes Agent 调用 LLM 工具")
    print(f"{'='*60}\n")
    
    # 占位符响应（实际使用时由 Hermes LLM 返回）
    return '{"chapters": [], "core_concepts": [], "key_insights": [], "key_cases": [], "key_quotes": []}'


def test_book_graph_generation(book_path: str, output_dir: str = None):
    """完整测试书籍知识图谱生成"""
    logger.info("="*60)
    logger.info("🧪 BookGraph Agent 测试")
    logger.info("="*60)
    
    # Step 1: 解析书籍
    parse_result = test_parse_book(book_path)
    if not parse_result:
        return
    
    # Step 2: 生成提示词
    book_title = parse_result.metadata.get('title', Path(book_path).stem)
    prompts = test_generate_prompt(parse_result, book_title)
    
    # Step 3: 调用 Hermes LLM（需要 Hermes Agent 执行）
    logger.info(f"\n📞 需要调用 Hermes LLM {len(prompts)} 次")
    
    all_analyses = []
    for i, prompt_data in enumerate(prompts):
        logger.info(f"\n📝 第 {i+1}/{len(prompts)} 块")
        
        # 这里需要 Hermes Agent 调用 LLM
        # 使用占位符演示流程
        analysis = test_hermes_llm_call(
            prompt_data['system'],
            prompt_data['user']
        )
        
        try:
            analysis_json = json.loads(analysis)
            all_analyses.append(analysis_json)
        except json.JSONDecodeError:
            logger.warning(f"⚠️  第 {i+1} 块解析失败")
    
    # Step 4: 生成 Markdown（演示）
    logger.info(f"\n📝 生成 Markdown 输出...")
    
    # 创建测试用的 BookGraph 对象
    from schemas.book_graph_schema import (
        BookGraph, BookMetadata, TimeBackground, CriticalAnalysis,
        DisciplineType
    )
    
    test_graph = BookGraph(
        metadata=BookMetadata(
            title=book_title,
            author=parse_result.metadata.get('author', 'Unknown'),
            author_intro='测试简介',
            discipline=DisciplineType.哲学,
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
    
    # 输出到文件
    if output_dir:
        output_path = Path(output_dir) / f"{Path(book_path).stem}_test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        logger.info(f"✅ Markdown 已写入：{output_path}")
    
    logger.info("\n" + "="*60)
    logger.info("✅ 测试完成")
    logger.info("="*60)
    
    return {
        "parse_result": parse_result,
        "prompts_count": len(prompts),
        "output_path": str(output_path) if output_dir else None
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="BookGraph Agent 测试脚本")
    parser.add_argument(
        "--input", "-i",
        type=str,
        default="/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/君主论.epub",
        help="书籍文件路径"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治哲学/书籍图谱/",
        help="输出目录"
    )
    
    args = parser.parse_args()
    
    result = test_book_graph_generation(args.input, args.output)
    
    if result:
        print(f"\n✅ 测试成功！")
        print(f"   解析字符：{len(result['parse_result'].content)}")
        print(f"   提示词数量：{result['prompts_count']}")
        if result['output_path']:
            print(f"   输出文件：{result['output_path']}")
