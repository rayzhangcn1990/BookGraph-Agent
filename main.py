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
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.llm_client import LLMClient, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT
from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from core.optimized_chunk_processor import process_book_chunks_native_async
from core.model_output_format_spec import parse_model_output
from core.local_evidence_preprocessor import LocalEvidencePreprocessor
from utils.parse_cache import get_cache
from utils.logger import setup_logger

logger = setup_logger("BookGraph-Optimized")


class QualityGateError(RuntimeError):
    """质量门检查失败。"""


def _safe_filename(name: str, max_bytes: int = 180) -> str:
    """生成安全文件名，避免书名中的路径分隔符和字节长度影响落盘。"""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(name or 'untitled'))
    safe = safe.strip(' ._') or 'untitled'
    digest = hashlib.sha1(safe.encode('utf-8')).hexdigest()[:8]
    suffix = f"_{digest}"
    budget = max(1, max_bytes - len(suffix.encode('utf-8')))

    encoded = safe.encode('utf-8')
    if len(encoded) > budget:
        encoded = encoded[:budget]
        safe = encoded.decode('utf-8', errors='ignore').strip(' ._') or 'untitled'

    return f"{safe}{suffix}"


def _quality_report_path(book_title: str) -> Path:
    """返回项目内质量报告路径。"""
    quality_dir = Path(__file__).resolve().parent / "logs" / "quality_reports"
    quality_dir.mkdir(parents=True, exist_ok=True)
    return quality_dir / f"{_safe_filename(book_title)}_quality_report.md"


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
    max_parallel: int = 1
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
        # Step 0: 初始化 LLM 客户端（提前初始化，用于元数据增强）
        llm_client = get_llm_client(config)

        # Step 1: 解析书籍 + 元数据增强
        book_parser = BookParser(
            str(book_path),
            config.get('parsing', {}),
            llm_client=llm_client,  # ponytail: 传入 LLM client 用于 fallback
        )

        # ponytail: 使用异步方法，支持元数据增强
        parse_result = await book_parser.parse_with_metadata_enrichment()

        if not parse_result.success:
            raise Exception(f"书籍解析失败: {parse_result.error}")

        logger.info(f"   ✅ 解析完成: {len(parse_result.content)}字符")

        # ponytail: 打印元数据增强结果
        if parse_result.metadata.get("author_intro"):
            logger.info(f"   📚 作者简介已增强 ({len(parse_result.metadata['author_intro'])}字)")
        if parse_result.metadata.get("source"):
            logger.info(f"   📊 元数据来源: {parse_result.metadata['source']}")

        # Step 2: 分块（语义分块）
        chunks = _semantic_chunking(parse_result, config)
        logger.info(f"   🧩 分块: {len(chunks)} 块")

        # Step 2.5: 本地 evidence 预处理（如果启用）
        local_hints_by_chunk = {}
        local_preprocessor_config = config.get('improvements', {}).get('local_evidence_preprocessor', {})
        if local_preprocessor_config.get('enabled', False):
            logger.info("   📍 启用本地 evidence 预处理")
            local_preprocessor = LocalEvidencePreprocessor(local_preprocessor_config)
            local_hints_by_chunk = await local_preprocessor.preprocess_chunks(
                book_title=parse_result.metadata.get('title', book_path.stem),
                chunks=chunks,
                max_parallel=int(local_preprocessor_config.get('max_parallel', 1)),
            )

        # Step 3: 并行处理 chunks（优化核心）
        # ponytail: llm_client 已在 Step 0 初始化，无需重复
        book_title = parse_result.metadata.get('title', book_path.stem)

        # 🔑 使用原生异步处理（Phase 3）
        from core.llm_client import get_async_llm_client
        async_llm_client = get_async_llm_client(config)

        # 🔑 检查是否启用结构化输出
        structured_output_enabled = config.get('improvements', {}).get('structured_output', {}).get('enabled', False)
        if structured_output_enabled:
            logger.info("   📋 启用结构化输出（强制 JSON Schema）")

        chunk_results = await process_book_chunks_native_async(
            async_llm_client,
            chunks,
            book_title,
            SYSTEM_PROMPT,
            CHUNK_ANALYSIS_PROMPT,
            max_parallel,
            local_hints_by_chunk=local_hints_by_chunk,
            structured_output_enabled=structured_output_enabled,
        )

        if not chunk_results:
            raise Exception("没有成功的 chunk 分析结果")

        logger.info(f"   ✅ Chunk 分析完成: {len(chunk_results)} 个成功")

        # 🔑 新增：预期章节数（用于质量校验）
        expected_chapters = len(parse_result.chapters) if parse_result.chapters else 0
        logger.info(f"   📖 预期章节数: {expected_chapters}")

        # Step 4: 综合分析（多轮拆分）
        # 🔑 PUA修复：拆分 synthesis 为多轮低复杂度任务
        # 根因：minimax 处理完整 BookGraph 复杂度太高，输出偷懒
        # 方案：拆成 5 轮，每轮输出 <2KB
        from core.multi_round_synthesis import synthesize_multi_round
        from core.two_stage_ingest import TwoStageIngest

        # 检查是否启用两阶段摄取
        two_stage_enabled = config.get('improvements', {}).get('two_stage_ingest', {}).get('enabled', False)
        quality_gate_config = config.get('improvements', {}).get('quality_gate', {})
        max_quality_retries = int(quality_gate_config.get('max_synthesis_retries', 2))

        async def run_synthesis(retry_feedback: str = ""):
            """运行综合阶段；质量重试时直接使用多轮合成并注入质量报告。"""
            if two_stage_enabled and not retry_feedback:
                logger.info("   🔄 使用两阶段 COT 摄取 (分析 → 生成)")
                content_summary = " ".join([chunk[1][:500] for chunk in chunks[:5]])
                ingest = TwoStageIngest(llm_client)
                two_stage_result = await ingest.process(
                    book_title=book_title,
                    author=parse_result.metadata.get('author', 'Unknown'),
                    discipline=discipline,
                    content_summary=content_summary
                )
                if two_stage_result:
                    return two_stage_result
                logger.warning("   ⚠️ 两阶段摄取失败，回退到多轮合成")

            return await synthesize_multi_round(
                llm_client,
                chunk_results,
                book_title,
                parse_result.metadata.get('author', 'Unknown'),
                discipline,
                expected_chapters,
                retry_feedback=retry_feedback
            )

        def build_book_graph(synthesis_data):
            """规范化综合结果并构造 BookGraph，失败时返回 schema 错误。"""
            from schemas.book_graph_schema import BookGraph

            synthesis_dict = llm_client._normalize_book_graph_data(
                synthesis_data,
                parse_result.metadata
            )

            try:
                graph = BookGraph(**synthesis_dict)
                logger.info(f"   ✅ BookGraph 构造成功（章节数: {len(graph.chapters)}）")
                return graph, ""
            except Exception as e:
                schema_error = str(e)[:200]
                logger.warning(f"   ⚠️ BookGraph 构造失败，使用宽松模式重建: {schema_error[:80]}")

            try:
                safe_dict = {k: v for k, v in synthesis_dict.items()
                             if k in BookGraph.model_fields}
                safe_dict.setdefault('chapters', [])
                safe_dict.setdefault('core_concepts', [])
                safe_dict.setdefault('key_insights', [])
                safe_dict.setdefault('key_cases', [])
                safe_dict.setdefault('key_quotes', [])
                safe_dict.setdefault('learning_path', {})
                safe_dict.setdefault('book_network', {})

                dict_fields = ['chapters', 'core_concepts', 'key_insights', 'key_cases', 'key_quotes']
                for f in dict_fields:
                    if isinstance(safe_dict.get(f), list):
                        safe_dict[f] = [item for item in safe_dict[f] if isinstance(item, dict)]

                if not isinstance(safe_dict.get('metadata'), dict):
                    safe_dict['metadata'] = {}
                meta = safe_dict['metadata']
                meta.setdefault('title', parse_result.metadata.get('title', book_title))
                meta.setdefault('author', parse_result.metadata.get('author', 'Unknown'))
                meta.setdefault('author_intro', '')
                meta.setdefault('discipline', discipline)

                if not isinstance(safe_dict.get('time_background'), dict):
                    safe_dict['time_background'] = {}
                tb = safe_dict['time_background']
                tb.setdefault('macro_background', '')
                tb.setdefault('micro_background', '')
                tb.setdefault('core_contradiction', '')

                if not isinstance(safe_dict.get('critical_analysis'), dict):
                    safe_dict['critical_analysis'] = {}
                ca = safe_dict['critical_analysis']
                ca.setdefault('feminist_perspective', '')
                ca.setdefault('postcolonial_perspective', '')
                ca.setdefault('ethical_boundaries', {})

                graph = BookGraph(**safe_dict)
                logger.info(f"   ✅ BookGraph 宽松构造成功（章节数: {len(graph.chapters)}）")
                return graph, schema_error
            except Exception as e2:
                schema_err = f"{schema_error}; 宽松构造失败：{str(e2)[:200]}"
                logger.warning(f"   ⚠️ 宽松构造仍失败: {schema_err[:200]}")
                return synthesis_dict, schema_err

        # Step 5: 写入前质量检查；失败时定向重试综合阶段，仍失败则阻止写入
        from core.book_graph_quality_checker import check_book_graph_quality

        book_graph = None
        quality_report = ""
        quality_passed = False

        for quality_attempt in range(max_quality_retries + 1):
            if quality_attempt > 0:
                logger.warning(
                    "   🔁 质量门未通过，定向重试综合阶段 (%s/%s)",
                    quality_attempt,
                    max_quality_retries
                )

            synthesis = await run_synthesis(quality_report if quality_attempt > 0 else "")
            if not synthesis:
                raise Exception("多轮综合分析失败")

            logger.info("   ✅ 综合分析完成")
            book_graph, schema_error = build_book_graph(synthesis)
            quality_data = book_graph.model_dump() if hasattr(book_graph, 'model_dump') else book_graph
            quality_passed, quality_report = check_book_graph_quality(quality_data, expected_chapters)
            if schema_error:
                quality_passed = False
                quality_report += f"\n**Schema 校验问题**:\n\n- ❌ BookGraph schema 校验失败：{schema_error}\n"
            if quality_passed:
                logger.info("   ✅ 写入前质量检查通过")
                break

        if not quality_passed:
            quality_path = _quality_report_path(book_title)
            try:
                quality_path.write_text(quality_report, encoding="utf-8")
            except OSError as save_error:
                logger.error("   ❌ 质量报告保存失败: %s", save_error)
                logger.error("%s", quality_report)
            logger.error("   ❌ 质量检查不通过: %s", quality_path)
            raise QualityGateError(f"质量检查不通过，已阻止写入: {quality_path}")

        # Step 6: 写入 Obsidian
        obsidian_writer = ObsidianWriter(config.get('obsidian', {}))
        graph_generator = GraphGenerator(config)

        markdown_content = graph_generator.generate_book_graph_markdown(book_graph)
        output_path = obsidian_writer.write_book_graph(book_graph, markdown_content)

        # 图洞察 (如果启用)
        insights_enabled = config.get('improvements', {}).get('graph_insights', {}).get('enabled', False)
        if insights_enabled and hasattr(book_graph, 'chapters') and book_graph.chapters:
            try:
                from core.graph_insights import build_insights_from_book_graph, format_insights_for_report
                logger.info("   🔍 生成图洞察报告...")
                insights_engine = build_insights_from_book_graph(book_graph)
                # 需要手动构建邻接表 (简化: 基于共现概念)
                # 这里暂时生成一个占位报告，后续可完善
                insights_report = format_insights_for_report({
                    "isolated": [],
                    "bridge": [],
                    "sparse_communities": []
                })
                insights_path = output_path.with_suffix('.insights.md')
                with open(insights_path, 'w', encoding='utf-8') as f:
                    f.write(insights_report)
                logger.info(f"   ✅ 图洞察报告: {insights_path}")
            except Exception as e:
                logger.warning(f"   ⚠️ 图洞察生成失败: {e}")

        # 摘要层索引 (如果启用)
        summary_enabled = config.get('improvements', {}).get('summary_index', {}).get('enabled', False)
        if summary_enabled:
            try:
                from core.summary_index import generate_chapter_summary, generate_book_summary
                output_dir = output_path.parent
                generate_chapter_summary(book_graph, output_dir)
                generate_book_summary(book_graph, output_dir)
            except Exception as e:
                logger.warning(f"   ⚠️ 摘要索引生成失败: {e}")

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
    语义分块 v2：按 Markdown 标题层级切分

    解决 LLM "中间迷失" 问题：
    - 原方案：chunk_size=30000 字符（约 7500 token）
    - 新方案：按 ## 标题切分，目标 2000-5000 token/chunk

    规则：
    - 每个 ## 标题作为一个独立 chunk
    - 过大章节按 ### 子标题再切分
    - 确保 LLM 能完整理解每个小节

    Args:
        parse_result: 解析结果（包含 Markdown 内容）
        config: 配置

    Returns:
        List: chunks [(index, content, label)]
    """
    content = parse_result.content

    # 🔑 新配置：基于 token 数而非字符数
    # 默认 4000 token（约 16000 字符）
    max_chunk_tokens = config.get('llm', {}).get('chunk_tokens', 4000)
    max_chunk_chars = max_chunk_tokens * 4  # 粗略估算

    chunks = []

    # 🔑 检查是否有 Markdown 标题结构（Docling 输出）
    has_markdown_headers = bool(re.search(r'^#{1,3}\s+', content, re.MULTILINE))

    if has_markdown_headers and parse_result.chapters and len(parse_result.chapters) > 1:
        # 有 Markdown 章节结构：按标题切分
        logger.info(f"   📑 使用 Markdown 标题分块（目标: {max_chunk_tokens} token）")

        for i, chapter in enumerate(parse_result.chapters):
            chapter_content = chapter.get("content", "")
            chapter_title = chapter.get("title", f"第{i+1}章")

            # 按 ## 标题切分章节内容
            sections = re.split(r'\n(?=## )', chapter_content)

            for j, section in enumerate(sections):
                # 估算 token 数（~4 字符/token）
                estimated_tokens = len(section) // 4

                if estimated_tokens <= max_chunk_tokens:
                    # 单个小节
                    label = f"[{chapter_title}]" if j == 0 else f"[{chapter_title} - Section {j+1}]"
                    chunks.append((len(chunks), section.strip(), label))
                else:
                    # 过大章节：按 ### 子标题再切分
                    subsections = re.split(r'\n(?=### )', section)

                    for k, sub in enumerate(subsections):
                        sub_label = f"[{chapter_title} - Section {j+1}.{k+1}]"
                        chunks.append((len(chunks), sub.strip(), sub_label))

    elif parse_result.chapters and len(parse_result.chapters) > 1:
        # 有章节结构但无 Markdown 标题：按章节分块（旧逻辑）
        logger.info(f"   📖 使用章节结构分块")

        for i, chapter in enumerate(parse_result.chapters):
            chapter_content = chapter.get("content", "")
            chapter_title = chapter.get("title", f"第{i+1}章")

            if len(chapter_content) <= max_chunk_chars:
                chunks.append((len(chunks), chapter_content, f"[{chapter_title}]"))
            else:
                # 大章节按段落分割
                paragraphs = chapter_content.split("\n\n")
                current_chunk = ""

                for para in paragraphs:
                    if len(current_chunk) + len(para) <= max_chunk_chars:
                        current_chunk += para + "\n\n"
                    else:
                        if current_chunk:
                            chunks.append((len(chunks), current_chunk, f"[{chapter_title} - 部分]"))
                        current_chunk = para + "\n\n"

                if current_chunk:
                    chunks.append((len(chunks), current_chunk, f"[{chapter_title} - 部分]"))

    else:
        # 无章节结构：按字符分块（回退方案）
        logger.info(f"   ⚠️ 无章节结构，按字符分块")

        for i in range(0, len(content), max_chunk_chars):
            chunk_content = content[i:i+max_chunk_chars]
            chunks.append((len(chunks), chunk_content, f"[块{len(chunks)+1}]"))

    # 🔑 统计
    avg_tokens = sum(len(c[1]) // 4 for c in chunks) / len(chunks) if chunks else 0
    logger.info(f"   📊 分块完成: {len(chunks)} 块，平均 {int(avg_tokens)} token")

    # 🔑 优化：合并小块（减少碎片化）
    if avg_tokens < 1000 and len(chunks) > 50:
        logger.info(f"   🔧 检测到碎片化分块（平均 {int(avg_tokens)} token），开始合并...")
        chunks = _merge_small_chunks(chunks, target_tokens=2000, min_tokens=500)
        new_avg_tokens = sum(len(c[1]) // 4 for c in chunks) / len(chunks) if chunks else 0
        logger.info(f"   ✅ 合并完成: {len(chunks)} 块，平均 {int(new_avg_tokens)} token")

    return chunks


def _merge_small_chunks(
    chunks: List[Tuple[int, str, str]],
    target_tokens: int = 2000,
    min_tokens: int = 500
) -> List[Tuple[int, str, str]]:
    """
    🔑 合并小块：减少碎片化，提高 LLM 调用效率

    Args:
        chunks: 原始分块列表 [(index, content, label)]
        target_tokens: 目标 token 数（合并后尽量接近）
        min_tokens: 最小 token 数（低于此值的小块必须合并）

    Returns:
        List[Tuple[int, str, str]]: 合并后的分块列表
    """
    if not chunks:
        return []

    merged = []
    current_buffer = []
    current_tokens = 0

    for chunk in chunks:
        _, content, label = chunk
        chunk_tokens = len(content) // 4

        should_flush = (
            current_buffer
            and current_tokens >= min_tokens
            and current_tokens + chunk_tokens > target_tokens
        )

        if should_flush:
            merged_content = "\n\n".join(c[1] for c in current_buffer)
            merged_label = current_buffer[0][2]
            merged.append((current_buffer[0][0], merged_content, merged_label))
            current_buffer = []
            current_tokens = 0

        current_buffer.append(chunk)
        current_tokens += chunk_tokens

    # 处理最后的缓冲区
    if current_buffer:
        merged_content = "\n\n".join(c[1] for c in current_buffer)
        merged_label = current_buffer[0][2]
        merged.append((current_buffer[0][0], merged_content, merged_label))

    return merged


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
    config: Dict,
    expected_chapters: int = 0  # 🔑 新增：预期章节数
) -> 'BookGraph':
    """
    综合分析所有 chunk 结果

    Args:
        chunk_results: chunk 分析结果列表
        book_title: 书名
        metadata: 书籍元数据
        discipline: 学科
        config: 配置
        expected_chapters: 预期章节数（用于质量校验，防止LLM偷懒合并章节）

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

    # 🔑 新增：章节覆盖率预警
    if expected_chapters > 0:
        coverage = chapter_count / expected_chapters
        if coverage < 0.8:
            logger.warning(f"   ⚠️ 章节覆盖率低: {chapter_count}/{expected_chapters} ({coverage*100:.0f}%)")
        else:
            logger.info(f"   ✅ 章节覆盖率: {coverage*100:.0f}%")

    # 精简输入（避免过长）- 🔑 修复：缩减到15KB，加速synthesis响应
    analyses_json = json.dumps(chunk_results, ensure_ascii=False)[:15000]

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
    SYNTHESIS_TIMEOUT = 1200  # 🔑 修复：synthesis 超时限制（20分钟，适应大模型响应）

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
                # 🔑 修复：使用 field_type 参数指定 synthesis 类型
                result, success, error_msg = parse_model_output(response, field_type="synthesis")

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

                    # 🔑 质量检查（强化版：传入预期章节数）
                    passed, quality_report = check_book_graph_quality(result, expected_chapters)

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
    parser.add_argument("--parallel", type=int, default=None, help="最大并行数（默认从配置读取，配置默认值为 8）")

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 🔑 max_parallel 优先级：命令行参数 > 配置文件 > 默认值 8
    if args.parallel is None:
        args.parallel = config.get('llm', {}).get('max_parallel', 8)
        logger.info(f"📐 max_parallel 从配置读取: {args.parallel}")

    # 清理过期缓存
    get_cache().clear_expired_cache()

    # 获取书籍路径
    input_path = Path(args.input)

    if args.batch or input_path.is_dir():
        # 批量处理
        book_paths = list(input_path.glob("*.epub")) + list(input_path.glob("*.pdf")) + list(input_path.glob("*.mobi"))
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