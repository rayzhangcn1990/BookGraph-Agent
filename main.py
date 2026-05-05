"""
优化版书籍解析入口

核心优化：
1. 全局 LLM 客户端单例（避免重复初始化）
2. 并行 chunk 处理（asyncio）
3. 缓存机制（断点续传）
4. 统一 JSON 解析（三层防护）
5. 精简日志（只输出关键信息）

使用方式：
    python optimized_main.py --input <书籍路径>
    python optimized_main.py --input <目录> --batch
"""

import asyncio
import argparse
import sys
import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.llm_client import LLMClient, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT
from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from core.optimized_chunk_processor import process_book_chunks_optimized
from core.model_output_format_spec import parse_model_output
from utils.parse_cache import get_cache
from utils.logger import setup_logger

logger = setup_logger("BookGraph-Optimized")


# ═══════════════════════════════════════════════════════════
# 全局客户端单例
# ═══════════════════════════════════════════════════════════

_llm_client: Optional[LLMClient] = None


def get_llm_client(config: Dict) -> LLMClient:
    """获取全局 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        llm_config = config.get('llm', {})
        _llm_client = LLMClient(llm_config)
        logger.info(f"✅ LLM 客户端初始化完成（模型: {_llm_client.model})")
    return _llm_client


def load_config(config_path: str = "config.yaml") -> Dict:
    """加载配置文件"""
    config_file = Path(config_path)
    if not config_file.exists():
        logger.warning(f"配置文件不存在：{config_file}，使用默认配置")
        return {}

    with open(config_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ═══════════════════════════════════════════════════════════
# 核心解析流程
# ═══════════════════════════════════════════════════════════

async def process_single_book_optimized(
    book_path: Path,
    config: Dict,
    discipline: str = "政治学",
    max_parallel: int = 4
) -> Dict:
    """
    优化版单书处理流程

    Args:
        book_path: 书籍路径
        config: 配置
        discipline: 学科
        max_parallel: 最大并行数

    Returns:
        Dict: 处理结果
    """
    start_time = datetime.now()
    logger.info(f"📖 开始处理: {book_path.name}")

    try:
        # Step 1: 解析书籍
        book_parser = BookParser(str(book_path), config.get('parsing', {}))
        parse_result = book_parser.parse()

        if not parse_result.success:
            raise Exception(f"书籍解析失败: {parse_result.error}")

        logger.info(f"   ✅ 解析完成: {len(parse_result.content)}字符")

        # Step 2: 分块（语义分块）
        chunks = _semantic_chunking(parse_result, config)
        logger.info(f"   🧩 分块: {len(chunks)} 块")

        # Step 3: 并行处理 chunks（优化核心）
        llm_client = get_llm_client(config)
        book_title = parse_result.metadata.get('title', book_path.stem)

        chunk_results = await process_book_chunks_optimized(
            llm_client,
            chunks,
            book_title,
            SYSTEM_PROMPT,
            CHUNK_ANALYSIS_PROMPT,
            max_parallel
        )

        if not chunk_results:
            raise Exception("没有成功的 chunk 分析结果")

        logger.info(f"   ✅ Chunk 分析完成: {len(chunk_results)} 个成功")

        # Step 4: 综合分析
        synthesis = await _synthesize_results(
            chunk_results,
            book_title,
            parse_result.metadata,
            discipline,
            config
        )

        logger.info(f"   ✅ 综合分析完成")

        # Step 5: 写入 Obsidian
        obsidian_writer = ObsidianWriter(config.get('obsidian', {}))
        graph_generator = GraphGenerator(config)

        markdown_content = graph_generator.generate_book_graph_markdown(synthesis)
        output_path = obsidian_writer.write_book_graph(synthesis, markdown_content)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ 处理完成: {output_path} ({elapsed:.1f}秒)")

        return {
            'success': True,
            'output_path': str(output_path),
            'chunks_processed': len(chunk_results),
            'elapsed_seconds': elapsed,
        }

    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ 处理失败: {str(e)[:200]} ({elapsed:.1f}秒)")
        return {
            'success': False,
            'error': str(e)[:200],
            'elapsed_seconds': elapsed,
        }


def _semantic_chunking(parse_result, config: Dict) -> List:
    """
    语义分块（基于章节结构）

    Args:
        parse_result: 解析结果
        config: 配置

    Returns:
        List: chunks [(index, content, label)]
    """
    max_chunk_size = config.get('llm', {}).get('chunk_size', 30000)
    chunks = []

    if parse_result.chapters and len(parse_result.chapters) > 1:
        # 有章节结构：按章节分块
        for i, chapter in enumerate(parse_result.chapters):
            content = chapter.get("content", "")
            title = chapter.get("title", f"第{i+1}章")

            if len(content) <= max_chunk_size:
                chunks.append((len(chunks), content, f"[{title}]"))
            else:
                # 大章节按段落分割
                paragraphs = content.split("\n\n")
                current_chunk = ""

                for para in paragraphs:
                    if len(current_chunk) + len(para) <= max_chunk_size:
                        current_chunk += para + "\n\n"
                    else:
                        if current_chunk:
                            chunks.append((len(chunks), current_chunk, f"[{title} - 部分]"))
                        current_chunk = para + "\n\n"

                if current_chunk:
                    chunks.append((len(chunks), current_chunk, f"[{title} - 部分]"))
    else:
        # 无章节结构：按字符分块
        full_content = parse_result.content
        for i in range(0, len(full_content), max_chunk_size):
            chunk_content = full_content[i:i+max_chunk_size]
            chunks.append((len(chunks), chunk_content, f"[块{len(chunks)+1}]"))

    return chunks


def _extract_chapters_list(chunk_results: List[Dict]) -> str:
    """
    🔑 根因修复：从 chunk_results 中提取章节列表（JSON 格式）

    Args:
        chunk_results: chunk 分析结果列表

    Returns:
        str: JSON 格式的章节列表字符串
    """
    chapters = []

    for result in chunk_results:
        # 从每个 chunk 中提取 chapter_summaries
        if 'chapter_summaries' in result and isinstance(result['chapter_summaries'], list):
            for ch in result['chapter_summaries']:
                if isinstance(ch, dict):
                    # 🔑 关键：保持 JSON 格式，不转换为纯文本
                    chapters.append({
                        'chapter_number': ch.get('chapter_number', '?'),
                        'title': ch.get('title', ''),
                        'core_argument': ch.get('core_argument', ''),
                        'underlying_logic': ch.get('underlying_logic', ''),
                        'related_books': ch.get('related_books', []),
                        'critical_questions': ch.get('critical_questions', [])
                    })

    # 🔑 返回 JSON 格式（而不是纯文本）
    if chapters:
        # 🔑 去重策略：保留所有章节（不去重，因为每个chunk可能分析不同部分）
        # 但限制总数（避免过长）
        max_chapters = 50  # 最多保留50个章节
        return json.dumps(chapters[:max_chapters], ensure_ascii=False)
    else:
        return "[]"  # 🔑 返回空数组（而不是"未检测到"）


async def _synthesize_results(
    chunk_results: List[Dict],
    book_title: str,
    metadata: Dict,
    discipline: str,
    config: Dict
) -> 'BookGraph':
    """
    综合分析所有 chunk 结果

    Args:
        chunk_results: chunk 分析结果列表
        book_title: 书名
        metadata: 书籍元数据
        discipline: 学科
        config: 配置

    Returns:
        BookGraph: 综合分析结果（返回 BookGraph 对象）
    """
    from schemas.book_graph_schema import BookGraph
    from core.book_graph_quality_checker import check_book_graph_quality

    llm_client = get_llm_client(config)

    # 🔑 根因修复：从 chunk_results 中提取章节列表
    chapters_list = _extract_chapters_list(chunk_results)
    # 🔑 修复：正确计算章节数（解析 JSON，而不是用 split('\n')）
    try:
        chapters_json = json.loads(chapters_list)
        chapter_count = len(chapters_json)
    except json.JSONDecodeError:
        chapter_count = 0
    logger.info(f"   📖 提取章节: {chapter_count} 个章节摘要")

    # 精简输入（避免过长）
    analyses_json = json.dumps(chunk_results, ensure_ascii=False)[:30000]

    prompt = SYNTHESIS_PROMPT.format(
        book_title=book_title,
        author=metadata.get('author', 'Unknown'),
        chapters_list=chapters_list,  # 🔑 修复：传递章节列表（不再硬编码空字符串）
        chapters_count=chapter_count,  # 🔑 新增：章节数量，强化指令
        all_chunk_analyses=analyses_json,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    # 智能重试（最多3次）
    SYNTHESIS_TIMEOUT = 600  # 🔑 新增：synthesis 超时限制（10分钟）

    for retry in range(3):
        try:
            # 🔑 新增：使用 asyncio.wait_for 包装，添加超时控制
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        llm_client._call_llm,
                        messages,
                        max_tokens=16384
                    ),
                    timeout=SYNTHESIS_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(f"   ⚠️ Synthesis API 超时 ({SYNTHESIS_TIMEOUT}秒)")
                delay = 30 * (retry + 1)
                logger.warning(f"   ⚠️ 综合分析超时，{delay}秒后重试")
                await asyncio.sleep(delay)
                continue

            if response:
                result, success, error_msg = parse_model_output(response, "synthesis")

                # 🔑 新增：诊断日志 - 记录解析失败时的原始响应
                if not success:
                    logger.warning(f"   ⚠️ Synthesis 解析失败: {error_msg}")
                    logger.warning(f"   ⚠️ 原始响应（前500字符）: {response[:500]}")
                    # 保存完整响应到临时文件
                    debug_path = Path(f"/tmp/synthesis_failed_{retry+1}.txt")
                    with open(debug_path, 'w') as f:
                        f.write(f"# Retry {retry+1}\n")
                        f.write(f"# Error: {error_msg}\n\n")
                        f.write(response)
                    logger.warning(f"   ⚠️ 完整响应已保存到: {debug_path}")

                if success and result:
                    # 🔑 关键修复：先规范化数据，填充所有必填字段的默认值
                    result = llm_client._normalize_book_graph_data(result, metadata)

                    # 🔑 质量检查（新增）
                    passed, quality_report = check_book_graph_quality(result)

                    if not passed:
                        logger.warning(f"   ⚠️ 内容质量不合格:\n{quality_report[:500]}")
                        # 质量不合格也触发重试
                        delay = 30 * (retry + 1)
                        logger.warning(f"   ⚠️ 综合分析质量不合格，{delay}秒后重试")
                        await asyncio.sleep(delay)
                        continue

                    # 🔑 将 Dict 转换为 BookGraph 对象
                    try:
                        book_graph = BookGraph(**result)
                        logger.info(f"   ✅ 质量检查通过（评分: {quality_report.split('质量评分')[1].split('/')[0].strip()}分）")
                        return book_graph
                    except Exception as e:
                        logger.warning(f"   ⚠️ BookGraph 构建失败: {e}")
                        # 继续重试

            # 失败等待后重试
            delay = 30 * (retry + 1)
            logger.warning(f"   ⚠️ 综合分析重试 ({retry+1}/3)，{delay}秒后重试")
            await asyncio.sleep(delay)

        except Exception as e:
            logger.warning(f"   ⚠️ 综合分析异常: {str(e)[:50]}")
            await asyncio.sleep(30)

    raise Exception("综合分析失败")


# ═══════════════════════════════════════════════════════════
# 批量处理
# ═══════════════════════════════════════════════════════════

async def process_batch_optimized(
    book_paths: List[Path],
    config: Dict,
    discipline: str = "政治学",
    max_parallel_books: int = 2
) -> List[Dict]:
    """
    优化版批量处理

    Args:
        book_paths: 书籍路径列表
        config: 配置
        discipline: 学科
        max_parallel_books: 最大并行书籍数

    Returns:
        List[Dict]: 所有处理结果
    """
    logger.info(f"📚 批量处理: {len(book_paths)} 本书")

    # 使用 semaphore 控制并发
    semaphore = asyncio.Semaphore(max_parallel_books)

    async def process_with_semaphore(book_path):
        async with semaphore:
            return await process_single_book_optimized(book_path, config, discipline)

    tasks = [process_with_semaphore(bp) for bp in book_paths]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 统计
    success_count = sum(1 for r in results if isinstance(r, Dict) and r.get('success'))
    logger.info(f"✅ 批量完成: {success_count}/{len(book_paths)} 成功")

    return results


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="优化版书籍解析")
    parser.add_argument("--input", required=True, help="书籍文件或目录路径")
    parser.add_argument("--discipline", default="政治学", help="学科分类")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--batch", action="store_true", help="批量处理模式")
    parser.add_argument("--parallel", type=int, default=4, help="最大并行数")

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 清理过期缓存
    get_cache().clear_expired_cache()

    # 获取书籍路径
    input_path = Path(args.input)

    if args.batch or input_path.is_dir():
        # 批量处理
        book_paths = list(input_path.glob("*.epub")) + list(input_path.glob("*.pdf"))
        if not book_paths:
            logger.error(f"未找到书籍文件: {input_path}")
            return

        results = asyncio.run(process_batch_optimized(book_paths, config, args.discipline))

    else:
        # 单书处理
        if not input_path.exists():
            logger.error(f"书籍不存在: {input_path}")
            return

        result = asyncio.run(process_single_book_optimized(input_path, config, args.discipline, args.parallel))

        if result.get('success'):
            logger.info(f"✅ 成功: {result['output_path']}")
        else:
            logger.error(f"❌ 失败: {result.get('error')}")


if __name__ == "__main__":
    main()