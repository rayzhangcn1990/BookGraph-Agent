"""
智能分层批量解析器

策略：
- 短书（< 50000字符）：单模型串行，多书并行（最多8本）
- 长书（≥ 50000字符）：多模型分块并行，单书独占

流程：
1. 预扫描所有书籍，分类为短书/长书
2. 短书队列：多书并行处理
3. 长书队列：逐本独占处理（每本内部多模型并行）
"""

import asyncio
import argparse
import sys
from pathlib import Path
import yaml
import json
from datetime import datetime
from typing import List, Dict, Tuple
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("SmartBatchParser")

from main import BookParser, process_single_book_optimized, ObsidianWriter, get_llm_client
from core.optimized_chunk_processor import process_book_chunks_optimized
from core.llm_client import SYNTHESIS_PROMPT, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT
from core.model_output_format_spec import repair_truncated_json, parse_model_output
from utils.hardware_config import get_hardware_profile, get_book_strategy, classify_book_size
from core.skills.skill_orchestrator import SkillOrchestrator, BookProcessingResult


# ═══════════════════════════════════════════════════════════
# 硬件自适应配置
# ═══════════════════════════════════════════════════════════

# 获取硬件画像
hardware_profile = get_hardware_profile()

# 动态设置阈值（基于硬件能力）
SHORT_BOOK_THRESHOLD = 30000  # 短书阈值
MAX_SHORT_BOOKS_PARALLEL = hardware_profile.recommended_parallel_books  # 短书并行数
MAX_LONG_BOOK_MODELS = hardware_profile.recommended_chunk_parallel      # 长书chunk并行数


@dataclass
class BookInfo:
    """书籍信息"""
    path: str
    name: str
    char_count: int
    is_long: bool
    status: str  # pending, running, completed, failed
    result: Dict = None


# ═══════════════════════════════════════════════════════════
# 短书处理（单模型串行，多书并行）
# ═══════════════════════════════════════════════════════════

async def process_short_book(
    book_info: BookInfo,
    config: Dict,
    discipline: str,
    semaphore: asyncio.Semaphore
) -> BookInfo:
    """处理短书（单模型，多书并行，带智能重试）"""
    async with semaphore:
        book_info.status = "running"
        start_time = datetime.now()

        logger.info(f"📚 [短书] 开始: {book_info.name}")

        # 🔑 智能重试（最多3次）
        max_retries = 3
        retry_delays = [30, 60, 90]  # 指数退避

        for retry in range(max_retries):
            try:
                # 使用现有的 process_single_book_optimized（单模型串行）
                result = await asyncio.to_thread(
                    process_single_book_optimized,
                    Path(book_info.path),
                    config,
                    discipline
                )

                book_info.result = result
                book_info.status = "completed"

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"✅ [短书] 完成: {book_info.name} ({duration:.1f}s)")
                return book_info

            except Exception as e:
                error_str = str(e)

                # 检查是否是限流错误（429）
                if '429' in error_str or 'throttling' in error_str.lower():
                    retry_delay = retry_delays[retry] * 2  # 限流等待加倍
                    logger.warning(f"⚠️ [短书] {book_info.name} 限流，{retry_delay}秒后重试 ({retry+1}/{max_retries})")
                else:
                    retry_delay = retry_delays[retry]
                    logger.warning(f"⚠️ [短书] {book_info.name} 失败: {error_str[:80]}, {retry_delay}秒后重试 ({retry+1}/{max_retries})")

                if retry < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue

        # 所有重试都失败
        book_info.status = "failed"
        book_info.result = {"error": f"重试耗尽 ({max_retries}次)", "last_error": error_str[:100]}
        logger.error(f"❌ [短书] 失败: {book_info.name} - 重试耗尽")

        return book_info


# ═══════════════════════════════════════════════════════════
# 长书处理（使用 SkillOrchestrator 并发执行各模块）
# ═══════════════════════════════════════════════════════════

async def process_long_book_with_skills(
    book_info: BookInfo,
    config: Dict,
    discipline: str,
    use_skill_orchestrator: bool = True
) -> BookInfo:
    """
    处理长书（使用 SkillOrchestrator 并发执行各模块）

    优势：
    - 模块并发执行（章节、概念、洞见、案例、金句同时处理）
    - 增量写入（每模块完成即写入 Obsidian）
    - 失败隔离（单个模块失败不影响其他模块）
    """
    book_info.status = "running"
    start_time = datetime.now()

    book_class = classify_book_size(book_info.char_count)

    logger.info("=" * 60)
    logger.info(f"📚 [{book_class.upper()}] 开始: {book_info.name} ({book_info.char_count} 字符)")
    logger.info("=" * 60)
    logger.info(f"   🎯 使用 SkillOrchestrator 并发处理")

    try:
        # 初始化 SkillOrchestrator
        orchestrator = SkillOrchestrator(config)
        llm_client = get_llm_client(config)
        obsidian_writer = ObsidianWriter(config.get("obsidian", {}))

        # 执行并发处理
        result = await orchestrator.process_book(
            {
                "path": book_info.path,
                "name": book_info.name,
                "char_count": book_info.char_count
            },
            llm_client,
            obsidian_writer,
            discipline
        )

        # 更新 book_info 状态
        if result.successful_skills == result.total_skills:
            book_info.status = "completed"
        elif result.successful_skills > 0:
            book_info.status = "partial"  # 部分成功
        else:
            book_info.status = "failed"

        book_info.result = {
            "output_path": str(result.output_path) if result.output_path else None,
            "successful_skills": result.successful_skills,
            "failed_skills": result.failed_skills,
            "errors": result.errors
        }

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ [Skill模式] 完成: {book_info.name} ({duration:.1f}s)")
        logger.info(f"   成功模块: {result.successful_skills}/{result.total_skills}")

    except Exception as e:
        book_info.status = "failed"
        book_info.result = {"error": str(e)}
        logger.error(f"❌ [Skill模式] 失败: {book_info.name} - {str(e)[:100]}")

    return book_info


# ═══════════════════════════════════════════════════════════
# 长书处理（传统方式 - 作为后备）
# ═══════════════════════════════════════════════════════════

async def process_long_book_legacy(
    book_info: BookInfo,
    config: Dict,
    discipline: str
) -> BookInfo:
    """处理长书（多模型分块并行，独占资源）"""
    book_info.status = "running"
    start_time = datetime.now()

    # 🔑 根据书籍大小获取自适应策略
    strategy = get_book_strategy(book_info.char_count, hardware_profile)
    book_class = classify_book_size(book_info.char_count)

    logger.info("=" * 60)
    logger.info(f"📚 [{book_class.upper()}] 开始: {book_info.name} ({book_info.char_count} 字符)")
    logger.info("=" * 60)
    logger.info(f"   策略: {strategy['description']}")
    logger.info(f"   并行chunks: {strategy['parallel_chunks']}, chunk大小: {strategy['chunk_size']}")

    try:
        # 1. 解析书籍
        book_parser = BookParser(book_info.path, config.get("parsing", {}))
        parse_result = book_parser.parse()

        if not parse_result.success:
            raise Exception(f"书籍解析失败: {parse_result.error}")

        # 2. 分块（使用策略参数）
        chunks = []
        max_chunk_size = strategy['chunk_size']

        for i, chapter in enumerate(parse_result.chapters):
            content = chapter.get("content", "")
            title = chapter.get("title", f"第{i+1}章")

            if len(content) <= max_chunk_size:
                chunks.append((len(chunks), content, title))
            else:
                for j in range(0, len(content), max_chunk_size):
                    sub_content = content[j:j+max_chunk_size]
                    chunks.append((len(chunks), sub_content, f"{title} - 部分{j//max_chunk_size+1}"))

        logger.info(f"   🧩 分块: {len(chunks)} 块")

        # 3. 多模型分块并行处理（使用策略参数）
        llm_client = get_llm_client(config)
        chunk_results = await process_book_chunks_optimized(
            llm_client,
            chunks,
            parse_result.metadata.get("title", book_info.name),
            SYSTEM_PROMPT,
            CHUNK_ANALYSIS_PROMPT,
            max_parallel=strategy['parallel_chunks']
        )

        # 4. 合并结果并增量更新
        all_analyses = chunk_results

        if not all_analyses:
            raise Exception("没有成功的 chunk 分析结果")

        # 🔑 增量更新：每批chunk完成后立即写入文件（而不是等到全部完成）
        # 先写入章节结构（如果有数据）
        from core.obsidian_writer import ObsidianWriter
        obsidian_writer = ObsidianWriter(config.get("obsidian", {}))

        # 提取章节信息并增量更新
        all_chapters = []
        for analysis in all_analyses:
            if "chapter_summaries" in analysis:
                for chapter in analysis.get("chapter_summaries", []):
                    title = chapter.get("title", "")
                    if title and title not in [c.get("title") for c in all_chapters]:
                        all_chapters.append(chapter)

        if all_chapters:
            # 生成章节markdown
            chapters_md = []
            for i, chapter in enumerate(all_chapters[:20], 1):  # 最多显示20章
                title = chapter.get("title", f"第{i}章")
                summary = chapter.get("summary", "")
                chapters_md.append(f"### 第{i}章：{title}\\n\\n{summary if summary else '（待补充）'}\\n\\n---")

            chapters_content = "\\n\\n".join(chapters_md)

            # 增量更新章节结构
            obsidian_writer.update_section(
                discipline,
                parse_result.metadata.get("title", book_info.name),
                "章节结构",
                chapters_content
            )
            logger.info(f"   📝 增量更新: 章节结构 ({len(all_chapters[:20])} 章)")

        # 5. 综合分析
        # 🔑 修复：parse_result.metadata 是 Pydantic BaseModel，需要转换为 dict
        # 同时确保所有必需字段存在
        raw_metadata = parse_result.metadata.model_dump() if hasattr(parse_result.metadata, 'model_dump') else dict(parse_result.metadata)
        metadata_dict = {
            "title": raw_metadata.get("title") or book_info.name,
            "author": raw_metadata.get("author") or "未知作者",
            "author_intro": raw_metadata.get("author_intro") or "",
            "discipline": discipline,
            "year_published": raw_metadata.get("year_published"),
            "category": raw_metadata.get("category") or [],
            "tags": raw_metadata.get("tags") or [],
            "related_books": raw_metadata.get("related_books") or []
        }
        book_title = metadata_dict["title"]
        logger.info(f"   📋 metadata_dict keys: {list(metadata_dict.keys())}")
        logger.info(f"   📋 author field: {metadata_dict.get('author', 'NOT FOUND')}")

        synthesis = await synthesize_results(
            all_analyses,
            book_title,
            metadata_dict,
            discipline,
            config
        )
        logger.info(f"   📋 synthesis result keys: {list(synthesis.keys()) if isinstance(synthesis, dict) else 'not dict'}")

        # 6. 写入 Obsidian（使用正确的接口）
        obsidian_writer = ObsidianWriter(config.get("obsidian", {}))

        # 🔑 修复：synthesis是dict，转换为BookGraph对象
        from schemas.book_graph_schema import BookGraph, BookMetadata, DisciplineType

        # 构建metadata
        if "metadata" in synthesis and isinstance(synthesis["metadata"], dict):
            # 从 synthesis 获取 metadata，确保必需字段存在
            synthesis_meta = synthesis["metadata"]
            # 🔑 使用原始 metadata_dict 作为 fallback（传入的参数）
            final_metadata = {
                "title": synthesis_meta.get("title") or book_title,
                "author": synthesis_meta.get("author") or metadata_dict.get("author") or "未知作者",
                "author_intro": synthesis_meta.get("author_intro") or metadata_dict.get("author_intro") or "",
                "discipline": synthesis_meta.get("discipline") or discipline,
                "year_published": synthesis_meta.get("year_published"),
                "category": synthesis_meta.get("category") or [],
                "tags": synthesis_meta.get("tags") or [],
                "related_books": synthesis_meta.get("related_books") or []
            }
            # 确保discipline是枚举类型
            if isinstance(final_metadata.get("discipline"), str):
                try:
                    final_metadata["discipline"] = DisciplineType(final_metadata["discipline"])
                except ValueError:
                    final_metadata["discipline"] = DisciplineType.哲学

            metadata = BookMetadata(**final_metadata)
        else:
            # 从参数构建metadata（使用metadata_dict，来自parse_result.metadata）
            # 🔑 确保所有必需字段存在
            metadata = BookMetadata(
                title=book_title,
                author=metadata_dict.get("author") or "未知作者",
                author_intro=metadata_dict.get("author_intro") or "",
                discipline=DisciplineType(discipline) if discipline in DisciplineType.__members__ else DisciplineType.哲学,
                year_published=metadata_dict.get("year_published"),
                category=metadata_dict.get("category") or [],
                tags=metadata_dict.get("tags") or [],
                related_books=metadata_dict.get("related_books") or []
            )

        # 构建BookGraph（允许缺少某些字段）
        try:
            book_graph = BookGraph(
                metadata=metadata,
                time_background=synthesis.get("time_background", {"macro_background": "", "micro_background": "", "core_contradiction": ""}),
                chapters=synthesis.get("chapters", []),
                core_concepts=synthesis.get("core_concepts", []),
                key_insights=synthesis.get("key_insights", []),
                key_cases=synthesis.get("key_cases", []),
                key_quotes=synthesis.get("key_quotes", []),
                critical_analysis=synthesis.get("critical_analysis", {"core_doubts": [], "feminist_perspective": "", "postcolonial_perspective": "", "ethical_boundaries": {}}),
                learning_path=synthesis.get("learning_path", {}),
                book_network=synthesis.get("book_network", {})
            )
        except Exception as e:
            logger.warning(f"⚠️ BookGraph构建失败: {str(e)[:100]}")
            # 🔑 修复：fallback 也必须构建 BookGraph 对象（ObsidianWriter 期望 BaseModel）
            # 使用最小化字段构建
            try:
                from schemas.book_graph_schema import TimeBackground
                book_graph = BookGraph(
                    metadata=metadata,  # 使用前面构建的 metadata
                    time_background=TimeBackground(
                        macro_background=synthesis.get("macro_background", ""),
                        micro_background=synthesis.get("micro_background", ""),
                        core_contradiction=synthesis.get("core_contradiction", "")
                    ),
                    chapters=[],  # 最小化：空列表
                    core_concepts=synthesis.get("core_concepts", []),
                    key_insights=synthesis.get("key_insights", []),
                    key_cases=[],  # 最小化
                    key_quotes=synthesis.get("golden_quotes", []),  # 尝试两种字段名
                    critical_analysis={"core_doubts": [], "feminist_perspective": "", "postcolonial_perspective": "", "ethical_boundaries": {}},
                    learning_path={},
                    book_network={}
                )
                logger.info("   ✅ 使用最小化 BookGraph 构建")
            except Exception as e2:
                logger.error(f"   ❌ 最小化 BookGraph 也失败: {str(e2)[:100]}")
                raise Exception(f"BookGraph 构建失败，无法写入: {str(e)[:100]}")

        # 生成 Markdown
        from core.graph_generator import GraphGenerator
        graph_generator = GraphGenerator(config)
        markdown_content = graph_generator.generate_book_graph_markdown(book_graph)

        # 写入文件
        output_path = obsidian_writer.write_book_graph(book_graph, markdown_content)

        book_info.result = {
            "output_path": str(output_path),
            "chunks_processed": len(all_analyses),
            "chunks_failed": len(chunks) - len(all_analyses),
        }

        book_info.status = "completed"

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ [长书] 完成: {book_info.name} ({duration:.1f}s)")
        logger.info(f"   输出: {output_path}")

    except Exception as e:
        book_info.status = "failed"
        book_info.result = {"error": str(e)}
        logger.error(f"❌ [长书] 失败: {book_info.name} - {str(e)[:100]}")

    return book_info


async def synthesize_results(
    all_analyses: list,
    book_title: str,
    metadata: dict,
    discipline: str,
    config: dict
) -> dict:
    """使用 LLMClient 进行综合分析（优化版）"""

    # 🔑 直接使用全局 LLMClient（避免重复选择 API 源和手动httpx调用）
    llm_client = get_llm_client(config)

    logger.info(f"   🧠 综合分析中... (使用全局 LLMClient)")

    # 🔑 智能压缩：只保留每个分析的核心信息（避免粗暴截断）
    compressed_analyses = []
    for analysis in all_analyses:
        compressed = {}
        # 只保留核心字段
        if "core_concepts" in analysis:
            compressed["core_concepts"] = [
                {"name": c.get("name"), "definition": c.get("definition", "")[:200]}
                for c in analysis.get("core_concepts", [])[:5]  # 每块最多5个概念
            ]
        if "key_insights" in analysis:
            compressed["key_insights"] = [
                {"insight": i.get("insight"), "explanation": i.get("explanation", "")[:150]}
                for i in analysis.get("key_insights", [])[:3]  # 每块最多3个洞见
            ]
        if "chapter_summaries" in analysis:
            compressed["chapter_summaries"] = [
                {"title": s.get("title"), "summary": s.get("summary", "")[:200]}
                for s in analysis.get("chapter_summaries", [])[:3]  # 每块最多3个章节
            ]
        compressed_analyses.append(compressed)

    analyses_json = json.dumps(compressed_analyses, ensure_ascii=False, indent=2)

    # 🔑 从chunk分析中提取所有章节标题，构建chapters_list
    all_chapter_titles = []
    for analysis in all_analyses:
        if "chapter_summaries" in analysis:
            for chapter in analysis.get("chapter_summaries", []):
                title = chapter.get("title", "")
                if title and title not in all_chapter_titles:
                    all_chapter_titles.append(title)

    chapters_list = "\n".join([f"{i+1}. {title}" for i, title in enumerate(all_chapter_titles)])
    if not chapters_list:
        chapters_list = "（未从chunk分析中提取到章节信息）"

    # 使用 SYNTHESIS_PROMPT
    # 🔑 修复：添加所有必需参数，包括chapters_list
    prompt = SYNTHESIS_PROMPT.format(
        book_title=book_title,
        author=metadata.get('author', 'Unknown'),
        chapters_list=chapters_list,
        all_chunk_analyses=analyses_json
    )

    # 🔑 调用 LLMClient（使用已有的重试机制）
    try:
        response = await asyncio.to_thread(
            llm_client._call_llm,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=16384
        )

        if response is None:
            raise Exception("LLMClient 返回空响应")

        # 🔑 使用统一 JSON 解析（三层防护）
        result, success, error_msg = parse_model_output(response)

        if success and result:
            logger.info(f"   ✅ 综合分析完成")
            return result
        else:
            # 🔑 解析失败，返回原始响应（不丢弃）
            logger.warning(f"   ⚠️ JSON解析失败，返回raw_response")
            return {
                "raw_response": response[:5000],
                "extraction_status": "partial",
                "error": error_msg[:100]
            }

    except Exception as e:
        logger.error(f"   ❌ 综合分析失败: {str(e)[:100]}")
        raise Exception(f"综合分析失败: {str(e)[:100]}")
# ═══════════════════════════════════════════════════════════
# 智能调度器
# ═══════════════════════════════════════════════════════════

class SmartBatchScheduler:
    """智能分层批量调度器"""

    def __init__(self, config: Dict, discipline: str):
        self.config = config
        self.discipline = discipline
        self.short_books: List[BookInfo] = []
        self.long_books: List[BookInfo] = []

    def scan_books(self, book_paths: List[str]) -> Tuple[List[BookInfo], List[BookInfo]]:
        """预扫描书籍，分类为短书/长书"""

        logger.info("=" * 60)
        logger.info("🔍 预扫描书籍")
        logger.info("=" * 60)

        short_books = []
        long_books = []

        for book_path in book_paths:
            path = Path(book_path)
            if not path.exists():
                logger.warning(f"⚠️ 跳过不存在: {book_path}")
                continue

            # 快速估算字符数（读取文件大小）
            file_size = path.stat().st_size

            # EPUB 通常压缩率约 50%
            estimated_chars = file_size * 0.5

            book_info = BookInfo(
                path=str(path),
                name=path.name,
                char_count=int(estimated_chars),
                is_long=estimated_chars >= SHORT_BOOK_THRESHOLD,
                status="pending"
            )

            if book_info.is_long:
                long_books.append(book_info)
                logger.info(f"   📖 [长书] {book_info.name} (~{int(estimated_chars/1000)}k字符)")
            else:
                short_books.append(book_info)
                logger.info(f"   📗 [短书] {book_info.name} (~{int(estimated_chars/1000)}k字符)")

        logger.info(f"\n📊 分类结果:")
        logger.info(f"   短书: {len(short_books)} 本")
        logger.info(f"   长书: {len(long_books)} 本")
        logger.info("=" * 60)

        self.short_books = short_books
        self.long_books = long_books

        return short_books, long_books

    async def run(self) -> List[BookInfo]:
        """执行分层处理"""

        all_results = []

        # 1. 短书并行处理
        if self.short_books:
            logger.info("\n" + "=" * 60)
            logger.info(f"📚 短书并行处理 ({len(self.short_books)} 本)")
            logger.info(f"   最大并行数: {MAX_SHORT_BOOKS_PARALLEL}")
            logger.info("=" * 60)

            semaphore = asyncio.Semaphore(MAX_SHORT_BOOKS_PARALLEL)

            tasks = [
                process_short_book(book, self.config, self.discipline, semaphore)
                for book in self.short_books
            ]

            short_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(short_results):
                if isinstance(result, Exception):
                    self.short_books[i].status = "failed"
                    self.short_books[i].result = {"error": str(result)}
                else:
                    self.short_books[i] = result

            all_results.extend(self.short_books)

        # 2. 长书逐本独占处理（使用 SkillOrchestrator）
        if self.long_books:
            logger.info("\n" + "=" * 60)
            logger.info(f"📚 长书处理 (SkillOrchestrator 模式) ({len(self.long_books)} 本)")
            logger.info(f"   每本并发模块数: {self.config.get('batch', {}).get('skill_parallel', 4)}")
            logger.info("=" * 60)

            for i, book in enumerate(self.long_books, 1):
                logger.info(f"\n[{i}/{len(self.long_books)}] 处理长书...")

                # 🔑 使用新的 SkillOrchestrator 模式
                result = await process_long_book_with_skills(book, self.config, self.discipline)

                if isinstance(result, Exception):
                    book.status = "failed"
                    book.result = {"error": str(result)}
                else:
                    self.long_books[i-1] = result

                all_results.extend(self.long_books)

        return all_results

    def print_summary(self, results: List[BookInfo]):
        """打印处理摘要"""

        print("\n" + "=" * 60)
        print("📊 智能分层处理摘要")
        print("=" * 60)

        short_completed = [r for r in results if not r.is_long and r.status == "completed"]
        short_failed = [r for r in results if not r.is_long and r.status == "failed"]
        long_completed = [r for r in results if r.is_long and r.status == "completed"]
        long_partial = [r for r in results if r.is_long and r.status == "partial"]
        long_failed = [r for r in results if r.is_long and r.status == "failed"]

        print(f"\n短书处理:")
        print(f"  ✅ 完成: {len(short_completed)} 本")
        print(f"  ❌ 失败: {len(short_failed)} 本")

        print(f"\n长书处理:")
        print(f"  ✅ 完成: {len(long_completed)} 本")
        print(f"  ⚠️ 部分成功: {len(long_partial)} 本")
        print(f"  ❌ 失败: {len(long_failed)} 本")

        if long_partial:
            print(f"\n  部分成功详情:")
            for r in long_partial:
                failed_skills = r.result.get("failed_skills", [])
                print(f"    - {r.name}: 失败模块 {failed_skills}")

        print(f"\n总计:")
        print(f"  ✅ 完成: {len(short_completed) + len(long_completed)} 本")
        print(f"  ⚠️ 部分成功: {len(long_partial)} 本")
        print(f"  ❌ 失败: {len(short_failed) + len(long_failed)} 本")

        # 保存报告
        report = {
            "timestamp": datetime.now().isoformat(),
            "short_books": {
                "completed": len(short_completed),
                "failed": len(short_failed),
                "details": [{"name": r.name, "status": r.status} for r in results if not r.is_long]
            },
            "long_books": {
                "completed": len(long_completed),
                "failed": len(long_failed),
                "details": [{"name": r.name, "status": r.status, "result": r.result} for r in results if r.is_long]
            }
        }

        report_path = Path("智能分层解析报告.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 详细报告: {report_path}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="智能分层批量解析书籍")
    parser.add_argument("--books", nargs="+", required=True, help="书籍文件路径")
    parser.add_argument("--discipline", default="政治学", help="学科分类")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")

    args = parser.parse_args()

    # 加载配置
    with open(args.config) as f:
        config = yaml.safe_load(f)

    # 创建调度器
    scheduler = SmartBatchScheduler(config, args.discipline)

    # 预扫描
    scheduler.scan_books(args.books)

    # 执行
    results = asyncio.run(scheduler.run())

    # 打印摘要
    scheduler.print_summary(results)


if __name__ == "__main__":
    main()

# ═══════════════════════════════════════════════════════════
# 向后兼容别名
# ═══════════════════════════════════════════════════════════

# process_long_book 别名指向旧版本（后备）
process_long_book = process_long_book_legacy