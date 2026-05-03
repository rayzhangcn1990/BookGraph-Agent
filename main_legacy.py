#!/usr/bin/env python3
"""
BookGraph Agent - 完整版本

使用 Hermes 或 Claude Code 的 LLM 工具调用，无需配置外部 API Key。

用法:
    python main.py --input <书籍文件路径>
    python main.py --input <书籍目录路径>  # 批量处理
    python main.py --input <文件路径> --discipline <学科>  # 手动指定学科
"""

import argparse
import sys
import os
import time
import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from schemas.book_graph_schema import DisciplineType

# 加载环境变量
load_dotenv()

from core.book_parser import BookParser
from core.graph_generator import GraphGenerator
from core.obsidian_writer import ObsidianWriter
from core.discipline_manager import DisciplineManager
from core.ocr_engine import OcrEngine
from core.llm_client import SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, BATCH_CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT, DISCIPLINE_DETECTION_PROMPT, LLMClient
from core.wikipedia_enricher import WikipediaEnricher
from core.incremental_evolver import IncrementalEvolver
from core.engine_selector import auto_select_engine
from utils.logger import setup_logger
from utils.cache import Cache
from utils.progress import ProgressTracker


# ═══════════════════════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════════════════════
logger = setup_logger("BookGraph-Agent")

# ═══════════════════════════════════════════════════════════
# 全局 LLM 客户端
# ═══════════════════════════════════════════════════════════
llm_client = None

def get_llm_client(config: Dict = None):
    """获取 LLM 客户端实例"""
    global llm_client
    if llm_client is None:
        llm_config = config.get('llm', {}) if config else {}
        llm_client = LLMClient(llm_config)
    return llm_client


# ═══════════════════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════════════════
def load_config(config_path: str = "config.yaml") -> Dict:
    """加载配置文件"""
    config_file = Path(config_path)
    
    if not config_file.exists():
        logger.warning(f"配置文件不存在：{config_file}，使用默认配置")
        return {}
    
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 替换环境变量
    if config and 'obsidian' in config:
        vault_path = config['obsidian'].get('vault_path', '')
        if vault_path.startswith('${') and vault_path.endswith('}'):
            env_var = vault_path[2:-1]
            config['obsidian']['vault_path'] = os.environ.get(env_var, '')
    
    return config


# ═══════════════════════════════════════════════════════════
# LLM 调用（通过 Hermes 工具或直接调用 DashScope API）
# ═══════════════════════════════════════════════════════════
def call_llm_via_tool(system_prompt: str, user_prompt: str, max_tokens: int = 16384, max_retries: int = 5) -> str:
    """
    调用 LLM 获取响应（带智能重试）

    使用配置的 LLM 客户端（Anthropic、DashScope 或 OpenAI）来处理请求。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户输入
        max_tokens: 最大输出 token 数
        max_retries: 最大重试次数（遇到限流时）

    Returns:
        str: LLM 响应文本
    """
    import random

    for attempt in range(max_retries):
        try:
            # 获取配置（从环境变量或默认值）
            config = load_config()
            client = get_llm_client(config)

            # 构建消息格式
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # 调用 LLM
            logger.info("📡 正在调用 LLM...")
            response = client._call_llm(messages, max_tokens=max_tokens)

            if response:
                logger.info(f"✅ LLM 响应成功（{len(response)} 字符）")
                return response
            else:
                logger.error("❌ LLM 调用失败，未获取响应")
                return None

        except Exception as e:
            error_str = str(e)

            # 处理 429 限流错误
            if '429' in error_str or 'throttling' in error_str.lower():
                if attempt < max_retries - 1:
                    wait_time = random.randint(180, 300)  # 等待 3-5 分钟
                    logger.warning(f"⚠️ API 限流 (尝试 {attempt+1}/{max_retries})")
                    logger.info(f"   💤 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ 重试 {max_retries} 次后仍然限流")
                    return None

            # 处理超时错误 - 华为蓝军自攻击：30分钟超时需重试
            elif 'timeout' in error_str.lower() or 'timed out' in error_str.lower():
                if attempt < max_retries - 1:
                    wait_time = random.randint(60, 120)  # 等待 1-2 分钟
                    logger.warning(f"⚠️ API 超时 (尝试 {attempt+1}/{max_retries})")
                    logger.info(f"   💤 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ 重试 {max_retries} 次后仍然超时")
                    return None

            else:
                logger.error(f"❌ LLM 调用异常: {e}")
                return None

    return None


# ═══════════════════════════════════════════════════════════
# 单本书处理
# ═══════════════════════════════════════════════════════════
def process_single_book(
    book_path: Path, 
    config: Dict,
    discipline_override: str = None,
    cache: Cache = None,
    progress: ProgressTracker = None
) -> Dict:
    """
    完整处理流程
    
    所有 LLM 调用通过 Hermes/Claude Code 工具实现。
    """
    start_time = time.time()
    book_path_str = str(book_path)
    
    # 检查进度（如果已处理则跳过）
    if progress and progress.is_processed(book_path_str):
        logger.info(f"⏭️  已处理，跳过：{book_path.name}")
        return {
            "success": True,
            "book_path": book_path_str,
            "skipped": True,
            "message": "已处理",
        }
    
    result = {
        "success": False,
        "book_path": book_path_str,
        "error": None,
    }
    
    try:
        # 确保 book_path 是 Path 对象
        book_path = Path(book_path) if isinstance(book_path, str) else book_path

        # ═══════════════════════════════════════════════════
        # Step 1: 初始化所有模块
        # ═══════════════════════════════════════════════════
        logger.info(f"📖 开始处理：{book_path.name}")

        obsidian_writer = ObsidianWriter(config.get('obsidian', {}))
        graph_generator = GraphGenerator(config)
        ocr_engine = OcrEngine(config.get('ocr', {}))

        discipline_manager = DisciplineManager(
            obsidian_writer=obsidian_writer,
            graph_generator=graph_generator,
            config=config,
        )

        # 初始化增量演化器（从知识基底复用已有概念）
        vault_path = config.get('obsidian', {}).get('vault_path', '')
        if vault_path:
            # 🔑 使用 ObsidianWriter 的路径计算逻辑，避免丢失中间层级
            discipline_path = obsidian_writer._get_discipline_path(discipline_override) if discipline_override else Path(config.get('obsidian', {}).get('graph_root', '📚 知识图谱'))
            kb_path = Path(vault_path) / discipline_path
            evolver = IncrementalEvolver(kb_path)
            logger.info(f"🔄 增量演化器已初始化，知识基底: {evolver.get_statistics()}")
        else:
            evolver = None
            logger.warning("未配置 Obsidian vault_path，增量演化功能禁用")

        # ═══════════════════════════════════════════════════
        # Step 2: 解析书籍
        # ═══════════════════════════════════════════════════
        logger.info("📄 解析书籍内容...")
        
        book_parser = BookParser(str(book_path), config.get('parsing', {}))
        parse_result = book_parser.parse()
        
        if not parse_result.success:
            raise Exception(f"书籍解析失败：{parse_result.error}")
        
        # 如果是图片型 PDF，使用 OCR
        if parse_result.is_image_based:
            logger.info("🔍 检测到图片型 PDF，启动 OCR 处理...")
            ocr_result = ocr_engine.process_pdf(str(book_path))
            
            if not ocr_result.get('success'):
                raise Exception(f"OCR 处理失败：{ocr_result.get('error')}")
            
            parse_result.content = ocr_result['content']
            parse_result.chapters = [{
                "chapter_id": "1",
                "title": "完整内容",
                "content": ocr_result['content'],
            }]
        
        logger.info(f"✅ 解析完成：{len(parse_result.content)}字符，{len(parse_result.chapters)}章节")
        
        # ═══════════════════════════════════════════════════
        # Step 3: 识别学科（通过 Hermes/Claude Code）
        # ═══════════════════════════════════════════════════
        if discipline_override:
            discipline = discipline_override
            logger.info(f"🏷️ 使用指定学科：{discipline}")
        else:
            logger.info("🏷️ 自动识别学科...")
            sample_content = parse_result.chapters[0]["content"][:2000] if parse_result.chapters else ""
            
            # 输出学科识别提示词
            discipline_prompt = DISCIPLINE_DETECTION_PROMPT.format(
                book_title=parse_result.metadata.get('title', book_path.stem),
                author=parse_result.metadata.get('author', 'Unknown'),
                first_chapter_content=sample_content,
            )
            
            print("\n" + "="*70)
            print("📝 [学科识别 - 需要 LLM 调用]")
            print("="*70)
            print(f"System: 你是一位学科分类专家。请准确判断书籍所属学科。")
            print(f"User: {discipline_prompt[:500]}...")
            print("="*70)
            print("⚠️  当前使用指定学科：政治学（需要 Hermes/Claude Code 调用时修改）")
            print("="*70 + "\n")

            # 临时使用指定学科
            discipline = "政治学"
            logger.info(f"🏷️ 学科：{discipline}")

        # ═══════════════════════════════════════════════════
        # Step 3.5: 增量抽取规划（复用已有知识）
        # ═══════════════════════════════════════════════════
        extraction_plan = None
        reusable_knowledge = {}

        if evolver:
            author = parse_result.metadata.get('author', 'Unknown')
            book_title = parse_result.metadata.get('title', book_path.stem)
            logger.info(f"🎯 增量抽取规划: {book_title} by {author}")

            extraction_plan = evolver.plan_extraction(book_title, author)

            if extraction_plan.reuse_concepts:
                reusable_knowledge = evolver.get_reusable_knowledge(extraction_plan.reuse_concepts)
                logger.info(f"✅ 可复用概念: {len(extraction_plan.reuse_concepts)}个，"
                           f"预估节省 {extraction_plan.estimated_tokens_saved} tokens")

        # ═══════════════════════════════════════════════════
        # Step 4: 确保目录结构存在
        # ═══════════════════════════════════════════════════
        obsidian_writer.ensure_discipline_structure(discipline)

        # ═══════════════════════════════════════════════════════════════════════
        # Step 4.5: 自动选择最优引擎
        # ═══════════════════════════════════════════════════════════════════════

        # 合并所有章节内容为完整文本（用于引擎选择）
        estimated_length = len("\n\n".join([ch["content"] for ch in parse_result.chapters]))

        # 获取知识基底统计
        kb_stats = evolver.get_statistics() if evolver else {'total_concepts': 0}

        # 自动选择引擎
        engine_rec = auto_select_engine(
            content_length=estimated_length,
            discipline=discipline,
            kb_concepts_count=kb_stats['total_concepts'],
            extraction_type="graph",
            has_complex_relations=True  # 政治学书籍通常有复杂关系
        )

        logger.info(f"🧠 引擎选择: {engine_rec.primary_engine.value}")
        logger.info(f"   原因: {engine_rec.reason}")
        logger.info(f"   速度: {engine_rec.estimated_speed} | 质量: {engine_rec.estimated_quality}")

        # ═══════════════════════════════════════════════════
        # Step 5: 分块分析（通过 Hermes/Claude Code）
        # ═══════════════════════════════════════════════════

        # 合并所有章节内容为完整文本
        full_content = "\n\n".join([ch["content"] for ch in parse_result.chapters])
        content_length = len(full_content)
        
        # 根据内容长度决定是否需要分块
        max_chunk_size = config.get('llm', {}).get('chunk_size', 30000)
        
        all_analyses = []
        
        if content_length <= max_chunk_size:
            # 短内容：一次性分析
            logger.info(f"🧠 整书分析中（{content_length}字符）...")
            
            prompt = CHUNK_ANALYSIS_PROMPT.format(
                book_title=parse_result.metadata.get('title', book_path.stem),
                chunk_content=full_content,  # 🔑 移除截断，发送完整内容
            )
            
            # 调用 LLM（通过 Hermes/Claude Code）
            analysis = call_llm_via_tool(SYSTEM_PROMPT, prompt)

            if analysis:
                try:
                    # 尝试提取 JSON
                    json_start = analysis.find('{')
                    json_end = analysis.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = analysis[json_start:json_end]
                    else:
                        json_str = analysis
                    all_analyses.append(json.loads(json_str))
                    logger.info(f"✅ 完成整书分析")
                except json.JSONDecodeError as e:
                    logger.error(f"❌ JSON 解析失败：{e}")
                    raise Exception(f"LLM 响应解析失败，请检查响应格式")
            else:
                # 当工具调用返回 None 时，需要等待 Hermes/Claude Code 处理
                logger.error("❌ 需要 Hermes/Claude Code 工具调用处理上述提示词")
                logger.error("   当前模式不支持自动调用外部 API")
                raise Exception("需要 LLM 工具调用响应，请使用 Hermes/Claude Code 模式")
                
        else:
            # 长内容：语义分块处理（优先使用章节边界，保持内容完整性）
            # 🔑 优化：语义分块 - 先按章节，再按段落，避免跨章节分割

            # 合并所有章节内容为完整文本
            full_content = "\n\n".join([ch["content"] for ch in parse_result.chapters])
            content_length = len(full_content)
            max_chunk_size = config.get('llm', {}).get('chunk_size', 25000)
            merge_threshold = config.get('llm', {}).get('merge_threshold', 15000)

            # 🔑 新增：语义分块（优先使用章节边界）
            chunks = []

            if parse_result.chapters and len(parse_result.chapters) > 1:
                # 有章节结构：按章节分块
                logger.info(f"🧩 语义分块中（{content_length}字符，{len(parse_result.chapters)}章节）...")

                for i, chapter in enumerate(parse_result.chapters):
                    chapter_content = chapter.get("content", "")
                    chapter_title = chapter.get("title", f"第{i+1}章")

                    if len(chapter_content) <= max_chunk_size:
                        # 章节完整，不拆分
                        chunks.append((i, chapter_content, f"[{chapter_title}]"))
                    else:
                        # 大章节：按段落边界拆分（保持语义完整性）
                        paragraphs = chapter_content.split("\n\n")
                        sub_chunks = []
                        current_chunk = ""

                        for para in paragraphs:
                            if len(current_chunk) + len(para) <= max_chunk_size:
                                current_chunk += para + "\n\n"
                            else:
                                if current_chunk:
                                    sub_chunks.append(current_chunk)
                                current_chunk = para + "\n\n"

                        if current_chunk:
                            sub_chunks.append(current_chunk)

                        # 添加子块
                        for j, sub_content in enumerate(sub_chunks):
                            chunks.append((len(chunks), sub_content, f"[{chapter_title} - 部分{j+1}]"))

                logger.info(f"   ✅ 语义分块：{len(chunks)} 块（基于 {len(parse_result.chapters)} 章节结构）")
            else:
                # 无章节结构：按字符数分块（原有逻辑）
                num_chunks = (content_length + max_chunk_size - 1) // max_chunk_size
                logger.info(f"🧩 字符分块中（{content_length}字符，预估{num_chunks}块）...")

                for i in range(num_chunks):
                    start = i * max_chunk_size
                    end = min((i + 1) * max_chunk_size, content_length)
                    chunks.append((i, full_content[start:end], ""))

            # 智能合并：小于 threshold 的 chunk 合并到相邻块
            final_chunks = []
            merged_count = 0
            for i, content, label in chunks:
                if len(content) < merge_threshold and final_chunks:
                    # 合并到前一个 chunk（保持语义连续）
                    prev_content, prev_label = final_chunks[-1][1], final_chunks[-1][2]
                    final_chunks[-1] = (final_chunks[-1][0], prev_content + "\n\n" + content, prev_label + " + " + label)
                    merged_count += 1
                else:
                    final_chunks.append((i, content, label))

            chunks = final_chunks
            logger.info(f"   🔧 智能合并：{merged_count} 个小块合并，最终 {len(chunks)} 块")

            num_chunks = len(chunks)

            # 🔑 优化：批量请求合并配置
            BATCH_SIZE = 1  # 🔑 不合并，每块单独处理，避免内容过大超时
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def process_chunk_batch(batch_chunks, book_title, batch_index):
                """批量处理多个 chunk（减少 API 调用次数）"""
                batch_size = len(batch_chunks)

                # 合并内容（用分隔符标记边界）
                merged_content = ""
                total_content_length = 0
                MAX_BATCH_CONTENT = 80000  # 🔑 降低到80KB，确保大batch被分割避免API超时

                for i, (idx, content, label) in enumerate(batch_chunks):
                    chunk_content = content  # 🔑 不截断单个chunk，保持完整性
                    merged_content += f"\n\n--- CHUNK BREAK (块 {idx+1} {label}) ---\n\n{chunk_content}"
                    total_content_length += len(chunk_content)

                # 🔑 修复：如果合并内容超过限制，回退到小块处理（按25000字符分割）
                if total_content_length > MAX_BATCH_CONTENT:
                    logger.warning(f"   ⚠️ 批量内容过长({total_content_length}字符)，回退到小块处理")
                    single_results = []
                    MAX_SINGLE_CHUNK = 25000  # 单块最大尺寸

                    for idx, content, label in batch_chunks:
                        if len(content) <= MAX_SINGLE_CHUNK:
                            # 小块直接处理
                            single_prompt = CHUNK_ANALYSIS_PROMPT.format(
                                book_title=book_title,
                                chunk_content=content,
                            )
                            single_analysis = call_llm_via_tool(SYSTEM_PROMPT, single_prompt, max_tokens=16384)
                            if single_analysis:
                                try:
                                    json_start = single_analysis.find('{')
                                    json_end = single_analysis.rfind('}') + 1
                                    if json_start >= 0 and json_end > json_start:
                                        single_result = json.loads(single_analysis[json_start:json_end])
                                    else:
                                        single_result = json.loads(single_analysis)
                                    single_results.append((idx, single_result))
                                    logger.info(f"   ✅ 单块 {idx+1} 完成")
                                except:
                                    single_results.append((idx, None))
                            else:
                                single_results.append((idx, None))
                        else:
                            # 大块分割成小块处理
                            sub_chunks = [(i, content[i:i+MAX_SINGLE_CHUNK]) for i in range(0, len(content), MAX_SINGLE_CHUNK)]
                            logger.info(f"   大块 {idx+1} ({len(content)}字符) 分割为 {len(sub_chunks)} 个小块")

                            for sub_idx, sub_content in sub_chunks:
                                single_prompt = CHUNK_ANALYSIS_PROMPT.format(
                                    book_title=book_title,
                                    chunk_content=sub_content,
                                )
                                single_analysis = call_llm_via_tool(SYSTEM_PROMPT, single_prompt, max_tokens=16384)
                                if single_analysis:
                                    try:
                                        json_start = single_analysis.find('{')
                                        json_end = single_analysis.rfind('}') + 1
                                        if json_start >= 0 and json_end > json_start:
                                            single_result = json.loads(single_analysis[json_start:json_end])
                                        else:
                                            single_result = json.loads(single_analysis)
                                        # 用 idx + sub_idx * 0.01 保持顺序
                                        single_results.append((idx + sub_idx * 0.01, single_result))
                                        logger.info(f"   ✅ 子块 {sub_idx+1}/{len(sub_chunks)} 完成")
                                    except:
                                        single_results.append((idx + sub_idx * 0.01, None))
                                else:
                                    single_results.append((idx + sub_idx * 0.01, None))

                    return single_results

                logger.info(f"   批量处理 {batch_index+1}: {batch_size} 个块合并为 1 个请求（{total_content_length}字符）")

                prompt = BATCH_CHUNK_ANALYSIS_PROMPT.format(
                    book_title=book_title,
                    batch_content=merged_content  # 🔑 移除截断限制
                )

                analysis = call_llm_via_tool(SYSTEM_PROMPT, prompt, max_tokens=32768)

                if analysis:
                    # 🔑 调试：打印 LLM 响应的前 2000 字符（用于排查格式问题）
                    print(f"\n{'='*60}")
                    print(f"[DEBUG] LLM 响应前2000字符:")
                    print(analysis[:2000])
                    print(f"{'='*60}\n")

                    try:
                        # 尝试提取 JSON
                        json_start = analysis.find('{')
                        json_end = analysis.rfind('}') + 1
                        if json_start >= 0 and json_end > json_start:
                            json_str = analysis[json_start:json_end]
                        else:
                            json_str = analysis

                        chunk_analysis = json.loads(json_str)
                        logger.info(f"   ✅ 批量 {batch_index+1} 完成（{batch_size} 块）")

                        # 解构批量结果为单 chunk 结果
                        if 'chunks_analysis' in chunk_analysis:
                            chunk_results = []
                            for i, chunk in enumerate(chunk_analysis['chunks_analysis']):
                                # 🔑 增加容错：chunk 可能是字符串或字典
                                if isinstance(chunk, dict):
                                    chunk_results.append((chunk.get('chunk_index', i), chunk))
                                elif isinstance(chunk, str):
                                    # 尝试解析字符串为 JSON
                                    try:
                                        chunk_dict = json.loads(chunk)
                                        chunk_results.append((chunk_dict.get('chunk_index', i), chunk_dict))
                                    except:
                                        # 无法解析，使用索引作为 fallback
                                        chunk_results.append((i, {"raw_content": chunk}))
                                else:
                                    chunk_results.append((i, chunk if chunk else {}))
                            return chunk_results
                        else:
                            # 如果 LLM 返回格式不规范，尝试单块解析
                            return [(batch_chunks[0][0], chunk_analysis)]
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️ 批量 {batch_index+1} JSON解析失败，尝试修复...")
                        logger.warning(f"   原始响应长度: {len(json_str)} 字符")
                        logger.warning(f"   JSON 提取范围: {json_start} - {json_end}")
                        logger.warning(f"   错误详情: {e}")
                        try:
                            # 补全括号
                            open_braces = json_str.count('{')
                            close_braces = json_str.count('}')
                            if open_braces > close_braces:
                                json_str_fixed = json_str + '}' * (open_braces - close_braces)
                                chunk_analysis = json.loads(json_str_fixed)
                                logger.info(f"   ✅ 批量 {batch_index+1} 修复成功")
                                if 'chunks_analysis' in chunk_analysis:
                                    chunk_results = []
                                    for i, chunk in enumerate(chunk_analysis['chunks_analysis']):
                                        # 🔑 增加容错：chunk 可能是字符串或字典
                                        if isinstance(chunk, dict):
                                            chunk_results.append((chunk.get('chunk_index', i), chunk))
                                        elif isinstance(chunk, str):
                                            try:
                                                chunk_dict = json.loads(chunk)
                                                chunk_results.append((chunk_dict.get('chunk_index', i), chunk_dict))
                                            except:
                                                chunk_results.append((i, {"raw_content": chunk}))
                                        else:
                                            chunk_results.append((i, chunk if chunk else {}))
                                    return chunk_results
                                else:
                                    return [(batch_chunks[0][0], chunk_analysis)]
                        except:
                            logger.error(f"❌ 批量 {batch_index+1} JSON 修复失败：{e}")
                            # 🔑 Fallback：回退到小块分析（按25000字符分割）
                            logger.warning(f"   ⚠️ 回退到小块分析模式...")
                            single_results = []
                            MAX_SINGLE_CHUNK = 25000

                            for idx, content, label in batch_chunks:
                                if len(content) <= MAX_SINGLE_CHUNK:
                                    single_prompt = CHUNK_ANALYSIS_PROMPT.format(
                                        book_title=book_title,
                                        chunk_content=content,
                                    )
                                    single_analysis = call_llm_via_tool(SYSTEM_PROMPT, single_prompt, max_tokens=16384)
                                    if single_analysis:
                                        try:
                                            json_start = single_analysis.find('{')
                                            json_end = single_analysis.rfind('}') + 1
                                            if json_start >= 0 and json_end > json_start:
                                                single_result = json.loads(single_analysis[json_start:json_end])
                                            else:
                                                single_result = json.loads(single_analysis)
                                            single_results.append((idx, single_result))
                                            logger.info(f"   ✅ 单块 {idx+1} 完成（fallback）")
                                        except:
                                            single_results.append((idx, None))
                                    else:
                                        single_results.append((idx, None))
                                else:
                                    # 大块分割
                                    sub_chunks = [(i, content[i:i+MAX_SINGLE_CHUNK]) for i in range(0, len(content), MAX_SINGLE_CHUNK)]
                                    logger.info(f"   大块 {idx+1} 分割为 {len(sub_chunks)} 个小块（fallback）")

                                    for sub_idx, sub_content in sub_chunks:
                                        single_prompt = CHUNK_ANALYSIS_PROMPT.format(
                                            book_title=book_title,
                                            chunk_content=sub_content,
                                        )
                                        single_analysis = call_llm_via_tool(SYSTEM_PROMPT, single_prompt, max_tokens=16384)
                                        if single_analysis:
                                            try:
                                                json_start = single_analysis.find('{')
                                                json_end = single_analysis.rfind('}') + 1
                                                if json_start >= 0 and json_end > json_start:
                                                    single_result = json.loads(single_analysis[json_start:json_end])
                                                else:
                                                    single_result = json.loads(single_analysis)
                                                single_results.append((idx + sub_idx * 0.01, single_result))
                                                logger.info(f"   ✅ 子块 {sub_idx+1}/{len(sub_chunks)} 完成（fallback）")
                                            except:
                                                single_results.append((idx + sub_idx * 0.01, None))
                                        else:
                                            single_results.append((idx + sub_idx * 0.01, None))

                            return single_results
                else:
                    logger.error(f"❌ 批量 {batch_index+1} 需要 LLM 工具调用")
                    return [(idx, None) for idx, _, _ in batch_chunks]

            # 🔑 优化：将 chunk 分组为 batch（每 batch 最多 3 个 chunk）
            chunk_batches = []
            for i in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[i:i+BATCH_SIZE]
                chunk_batches.append((i // BATCH_SIZE, batch))

            logger.info(f"   📦 批量分组：{len(chunks)} 块 → {len(chunk_batches)} 个请求（预期节省 {len(chunks) - len(chunk_batches)} 次 API 调用）")

            # 并行处理所有 batch（最多 2 个并发，避免 429）
            batch_results = []
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(process_chunk_batch, batch, parse_result.metadata.get('title', book_path.stem), batch_idx)
                           for batch_idx, batch in chunk_batches]

                for future in as_completed(futures):
                    batch_chunk_results = future.result()
                    if batch_chunk_results:  # 🔑 修复：检查None避免TypeError
                        for idx, chunk_res in batch_chunk_results:
                            if chunk_res:
                                batch_results.append((idx, chunk_res))
                    else:
                        logger.warning(f"   ⚠️ 一个batch返回None，跳过")

            # 按顺序排序结果
            batch_results.sort(key=lambda x: x[0])
            all_analyses = [r for idx, r in batch_results]

            # 华为蓝军自攻击：允许部分块失败，只要完成 ≥80% 就继续
            success_rate = len(all_analyses) / len(chunks)
            if success_rate < 0.8:
                logger.error(f"❌ 块解析成功率过低：{success_rate:.1%} ({len(all_analyses)}/{len(chunks)})")
                raise Exception(f"块解析成功率过低：{success_rate:.1%}")
            elif len(all_analyses) < len(chunks):
                logger.warning(f"⚠️ 部分块解析失败，但成功率达标：{success_rate:.1%} ({len(all_analyses)}/{len(chunks)})")
                logger.warning(f"   知识图谱数据可能不完整，但继续生成")

            logger.info(f"✅ 完成 {len(all_analyses)}/{len(chunks)} 个分块分析（成功率：{success_rate:.1%}）")
            logger.info(f"   💰 批量合并节省：{len(chunks) - len(chunk_batches)} 次 API 调用")
        
        # ═══════════════════════════════════════════════════
        # Step 6: 综合生成 BookGraph（通过 LLM 调用）
        # ═══════════════════════════════════════════════════
        logger.info("🔮 综合生成知识图谱...")

        # 🔑 根本方案：提取完整章节列表，强制保留
        chapters_list_str = ""
        if parse_result.chapters:
            chapters_list = []
            for i, ch in enumerate(parse_result.chapters):
                title = ch.get('title', f'第{i+1}章')
                chapters_list.append(f"{i+1}. {title}")
            chapters_list_str = "\n".join(chapters_list)
            logger.info(f"   ✅ 章节列表提取完成: {len(parse_result.chapters)} 章")
            logger.info(f"   章节列表预览: {chapters_list_str[:200]}...")

        # 根据传入的学科名称获取对应的 DisciplineType
        try:
            discipline_enum = DisciplineType(discipline)
        except ValueError:
            # 如果传入的学科不在枚举中，默认使用政治学
            discipline_enum = DisciplineType.政治学
            logger.warning(f"⚠️  未知学科 '{discipline}'，使用默认学科：政治学")

        # 🔑 移除截断，发送完整分析结果（避免章节丢失）
        analyses_str = json.dumps(all_analyses, ensure_ascii=False, indent=2)
        logger.info(f"   综合生成输入长度: {len(analyses_str)} 字符")

        # 🔑 新增：如果综合输入超过阈值，分段处理避免超时
        MAX_SYNTHESIS_INPUT = 80000  # 与 MAX_BATCH_CONTENT 保持一致
        synthesis_responses = []

        if len(analyses_str) > MAX_SYNTHESIS_INPUT:
            logger.warning(f"   ⚠️ 综合输入过长({len(analyses_str)}字符)，分段处理")
            # 分割all_analyses为多个部分
            synthesis_parts = []
            current_part = []
            current_length = 0

            for analysis in all_analyses:
                analysis_str = json.dumps(analysis, ensure_ascii=False)
                if current_length + len(analysis_str) > MAX_SYNTHESIS_INPUT and current_part:
                    synthesis_parts.append(current_part)
                    current_part = []
                    current_length = 0
                current_part.append(analysis)
                current_length += len(analysis_str)

            if current_part:
                synthesis_parts.append(current_part)

            logger.info(f"   📦 分割为 {len(synthesis_parts)} 部分")
            for i, part in enumerate(synthesis_parts):
                part_str = json.dumps(part, ensure_ascii=False, indent=2)
                part_prompt = SYNTHESIS_PROMPT.format(
                    book_title=parse_result.metadata.get('title', book_path.stem),
                    author=parse_result.metadata.get('author', 'Unknown'),
                    chapters_list=chapters_list_str,
                    all_chunk_analyses=part_str,
                )
                logger.info(f"   📡 处理部分 {i+1}/{len(synthesis_parts)} ({len(part_str)}字符)")
                part_response = call_llm_via_tool(SYSTEM_PROMPT, part_prompt, max_tokens=8192)
                if part_response:
                    synthesis_responses.append(part_response)
                    logger.info(f"   ✅ 部分 {i+1} 完成")

            # 合成多个部分的响应
            if synthesis_responses:
                combined_prompt = f"""请综合以下{len(synthesis_responses)}个部分的分析结果，生成统一的书籍知识图谱（包含metadata、chapters、core_concepts、key_insights）：

书籍：{parse_result.metadata.get('title', book_path.stem)}
作者：{parse_result.metadata.get('author', 'Unknown')}
章节列表：
{chapters_list_str}

各部分分析：
"""
                for i, resp in enumerate(synthesis_responses):
                    combined_prompt += f"\n--- 部分{i+1} ---\n{resp}\n"

                logger.info(f"   🔮 合成 {len(synthesis_responses)} 个部分结果")
                llm_response = call_llm_via_tool(SYSTEM_PROMPT, combined_prompt, max_tokens=8192)
            else:
                llm_response = None
        else:
            synthesis_prompt = SYNTHESIS_PROMPT.format(
                book_title=parse_result.metadata.get('title', book_path.stem),
                author=parse_result.metadata.get('author', 'Unknown'),
                chapters_list=chapters_list_str,  # 🔑 传入完整章节列表
                all_chunk_analyses=analyses_str,
            )
            llm_response = call_llm_via_tool(SYSTEM_PROMPT, synthesis_prompt, max_tokens=8192)  # 🔑 降低到8K，避免API超时

        # ═══════════════════════════════════════════════════════════
        # 重要：当 LLM 工具调用返回 None 时，表示需要 Hermes/Claude Code 处理
        # 此时不应继续使用模板默认值，而是等待工具调用响应
        # ═══════════════════════════════════════════════════════════
        if not llm_response:
            logger.error("❌ LLM 工具调用未获取响应")
            logger.error("   请在 Hermes/Claude Code 对话中处理上述提示词")
            logger.error("   或使用正确配置的 API Key 后重新运行")
            result["error"] = "需要 LLM 工具调用响应"
            return result
        
        book_graph_data = {}
        
        if llm_response:
            logger.info(f"✅ LLM 响应获取成功，解析 JSON...")
            try:
                # 尝试提取 JSON
                json_start = llm_response.find('{')
                json_end = llm_response.rfind('}') + 1

                if json_start >= 0 and json_end > json_start:
                    json_str = llm_response[json_start:json_end]
                else:
                    json_str = llm_response

                book_graph_data = json.loads(json_str)
                logger.info(f"✅ JSON 解析成功")
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️  JSON 解析失败：{e}，尝试修复...")
                # 🔑 根本修复：补全括号并重试
                try:
                    open_braces = json_str.count('{')
                    close_braces = json_str.count('}')
                    if open_braces > close_braces:
                        json_str_fixed = json_str + '}' * (open_braces - close_braces)
                        book_graph_data = json.loads(json_str_fixed)
                        logger.info(f"✅ JSON 修复成功（补全括号）")
                    else:
                        # 🔑 备用方案：使用分块分析结果直接构建
                        logger.warning("⚠️  JSON修复失败，使用分块分析结果")
                        book_graph_data = {
                            'metadata': {'title': parse_result.metadata.get('title', book_path.stem)},
                            'chapters': [],
                            'core_concepts': [],
                            'key_insights': [],
                        }
                        # 从all_analyses提取概念和洞见
                        for analysis in all_analyses:
                            if isinstance(analysis, dict):
                                if 'core_concepts' in analysis:
                                    for c in analysis.get('core_concepts', []):
                                        if isinstance(c, dict) and 'concept' in c:
                                            book_graph_data['core_concepts'].append({
                                                'name': c.get('concept', ''),
                                                'definition': c.get('definition', ''),
                                            })
                                if 'key_insights' in analysis:
                                    for i in analysis.get('key_insights', []):
                                        if isinstance(i, dict) and 'insight' in i:
                                            book_graph_data['key_insights'].append({
                                                'title': i.get('insight', ''),
                                                'description': i.get('logic_chain', ''),
                                            })
                        logger.info(f"✅ 从分块分析提取：{len(book_graph_data.get('core_concepts', []))}概念，{len(book_graph_data.get('key_insights', []))}洞见")
                except Exception as fix_error:
                    logger.error(f"❌ JSON 修复失败：{fix_error}")
                    book_graph_data = {}
        else:
            logger.warning("⚠️  LLM 调用未获取响应")
        
        # ═══════════════════════════════════════════════════════════════════════
        # Wikipedia 信息补充（减少 LLM 调用）
        # ═══════════════════════════════════════════════════════════════════════
        wiki_enricher = WikipediaEnricher()
        wiki_info = None
        author = parse_result.metadata.get('author', 'Unknown')
        book_title = parse_result.metadata.get('title', book_path.stem)

        if author != 'Unknown':
            logger.info(f"📚 Wikipedia 补充作者信息: {author}")
            try:
                wiki_info = wiki_enricher.enrich_book_metadata(book_title, author)
            except Exception as e:
                logger.warning(f"⚠️ Wikipedia 补充失败（跳过继续处理）: {e}")
                wiki_info = None

        # 从 LLM 响应构建 BookGraph，如果失败则使用合理的默认值
        from schemas.book_graph_schema import (
            BookGraph, BookMetadata, TimeBackground, CriticalAnalysis,
            ChapterSummary, CoreConcept, KeyInsight, KeyCase, KeyQuote
        )

        # 提取元数据（优先使用 Wikipedia 信息）
        meta = book_graph_data.get('metadata', {})
        author_intro = meta.get('author_intro')
        if not author_intro and wiki_info and wiki_info.author_intro:
            author_intro = wiki_info.author_intro
            logger.info(f"✅ 使用 Wikipedia 作者简介（节省约 {len(wiki_info.author_intro)*0.5:.0f} tokens）")
        if not author_intro:
            author_intro = f"{author}是本书的作者，其思想和理论对{discipline}领域产生了重要影响。"

        book_graph = BookGraph(
            metadata=BookMetadata(
                title=meta.get('title', book_title),
                author=meta.get('author', author),
                author_intro=author_intro,
                year_published=meta.get('year_published'),
                category=meta.get('category', [discipline]),
                discipline=discipline_enum,
                tags=meta.get('tags', [discipline, '知识图谱']),
                related_books=meta.get('related_books', [])
            ),
            time_background=TimeBackground(
                macro_background=book_graph_data.get('time_background', {}).get('macro_background', 
                    f"本书创作于{discipline}领域发展的重要时期，反映了当时学术界对于相关问题的深入思考。"),
                micro_background=book_graph_data.get('time_background', {}).get('micro_background',
                    f"作者在创作本书时，基于其自身的学术背景和研究经历，对{discipline}领域的核心问题进行了系统性阐述。"),
                core_contradiction=book_graph_data.get('time_background', {}).get('core_contradiction',
                    f"本书所回应的核心矛盾是{discipline}领域中的基础理论问题，作者试图提供新的分析框架和解决方案。")
            ),
            chapters=[],
            core_concepts=[],
            key_insights=[],
            key_cases=[],
            key_quotes=[],
            critical_analysis=CriticalAnalysis(
                core_doubts=book_graph_data.get('critical_analysis', {}).get('core_doubts', []),
                feminist_perspective=book_graph_data.get('critical_analysis', {}).get('feminist_perspective',
                    f"从女性主义视角审视，本书的理论框架可以进一步探讨性别维度在{discipline}领域中的作用和影响。"),
                postcolonial_perspective=book_graph_data.get('critical_analysis', {}).get('postcolonial_perspective',
                    f"从后殖民主义视角审视，本书的理论可以置于全球知识生产的语境中，考察其文化背景和普适性。"),
                ethical_boundaries=book_graph_data.get('critical_analysis', {}).get('ethical_boundaries', {
                    "reasonable": "本书的理论在合理范围内具有重要的学术价值和应用意义。",
                    "dangerous": "需要注意避免理论的极端化应用和简化解读。",
                    "institutional_safeguards": "建议结合多元视角和批判性思维进行理解和应用。"
                })
            ),
            learning_path=book_graph_data.get('learning_path', {
                "beginner": ["阅读本书前言和导论部分", "了解作者基本思想和学术背景"],
                "intermediate": ["深入阅读核心章节", "理解关键概念和理论框架"],
                "advanced": ["批判性审视理论局限", "与其他相关著作对比阅读"],
                "practice": ["将理论应用于实际问题分析", "参与相关学术讨论"]
            }),
            book_network=book_graph_data.get('book_network', {})
        )
        
        # 解析章节摘要
        chapters_data = book_graph_data.get('chapters', [])
        if chapters_data and isinstance(chapters_data, list):
            for ch in chapters_data:
                if isinstance(ch, dict):
                    book_graph.chapters.append(ChapterSummary(
                        chapter_number=str(ch.get('chapter_number', '')),
                        title=ch.get('title', '未知章节'),
                        core_argument=ch.get('core_argument', '本章探讨了书中的核心议题。'),
                        underlying_logic=ch.get('underlying_logic', '作者通过逻辑推理展开论述。'),
                        related_books=ch.get('related_books', []),
                        critical_questions=ch.get('critical_questions', [])
                    ))
        elif not chapters_data and parse_result.chapters:
            # Fallback: 从解析结果提取章节信息
            logger.info(f"📋 使用解析结果的 {len(parse_result.chapters)} 个章节作为 fallback")
            for idx, ch in enumerate(parse_result.chapters, 1):
                book_graph.chapters.append(ChapterSummary(
                    chapter_number=str(idx),
                    title=ch.get('title', f'第{idx}章'),
                    core_argument='本章探讨了书中的核心议题。',
                    underlying_logic='作者通过逻辑推理展开论述。',
                    related_books=[],
                    critical_questions=[]
                ))
        
        # 解析核心概念
        concepts_data = book_graph_data.get('core_concepts', [])
        if concepts_data and isinstance(concepts_data, list):
            for c in concepts_data:
                if isinstance(c, dict):
                    book_graph.core_concepts.append(CoreConcept(
                        name=c.get('name', '未知概念'),
                        definition=c.get('definition', '该概念是本书的核心理论要素。'),
                        deep_meaning=c.get('deep_meaning', '这一概念具有深层次的理论内涵。'),
                        underlying_logic=c.get('underlying_logic', '概念的底层逻辑体现了作者的思维方式。'),
                        development_stages=c.get('development_stages', []),
                        core_drivers=c.get('core_drivers', []),
                        critical_review=c.get('critical_review', '该概念在学术界存在多种解读和评价。'),
                        related_books=c.get('related_books', [])
                    ))
        
        # 解析关键洞见
        insights_data = book_graph_data.get('key_insights', [])
        if insights_data and isinstance(insights_data, list):
            for i in insights_data:
                if isinstance(i, dict):
                    book_graph.key_insights.append(KeyInsight(
                        title=i.get('title', '关键洞见'),
                        description=i.get('description', '这是作者提出的重要观点。'),
                        underlying_logic=i.get('underlying_logic', '该洞见基于作者的逻辑推理。'),
                        deep_assumptions=i.get('deep_assumptions', []),
                        related_books=i.get('related_books', []),
                        controversies=i.get('controversies', '这一观点在学术界存在不同看法。'),
                        multi_perspectives=i.get('multi_perspectives', {})
                    ))
        
        # 解析关键案例
        cases_data = book_graph_data.get('key_cases', [])
        if cases_data and isinstance(cases_data, list):
            for c in cases_data:
                if isinstance(c, dict):
                    book_graph.key_cases.append(KeyCase(
                        name=c.get('name', '未知案例'),
                        source_chapter=c.get('source_chapter', '未知章节'),
                        event_description=c.get('event_description', '这是一个具体的案例描述。'),
                        development_stages=c.get('development_stages', []),
                        core_drivers=c.get('core_drivers', []),
                        related_books=c.get('related_books', []),
                        historical_limitations=c.get('historical_limitations', '案例存在特定的历史背景和局限性。')
                    ))
        
        # 解析金句
        quotes_data = book_graph_data.get('key_quotes', [])
        if quotes_data and isinstance(quotes_data, list):
            for q in quotes_data:
                if isinstance(q, dict):
                    book_graph.key_quotes.append(KeyQuote(
                        text=q.get('text', ''),
                        chapter=q.get('chapter', '未知章节'),
                        core_theme=q.get('core_theme', '核心主题'),
                        background_context=q.get('background_context', '时代背景'),
                        underlying_logic=q.get('underlying_logic', '底层逻辑'),
                        common_misreading=q.get('common_misreading'),
                        related_books=q.get('related_books', [])
                    ))
        
        logger.info(f"✅ 知识图谱生成完成：{len(book_graph.chapters)}章节，{len(book_graph.core_concepts)}概念，{len(book_graph.key_insights)}洞见")
        
        # ═══════════════════════════════════════════════════
        # Step 7: 生成 Markdown
        # ═══════════════════════════════════════════════════
        logger.info("📝 生成 Markdown 内容...")
        
        markdown_content = graph_generator.generate_book_graph_markdown(book_graph)
        
        # ═══════════════════════════════════════════════════
        # Step 8: 写入 Obsidian
        # ═══════════════════════════════════════════════════
        logger.info("💾 写入 Obsidian...")
        
        output_path = obsidian_writer.write_book_graph(book_graph, markdown_content)
        result["output_path"] = str(output_path)
        
        # ═══════════════════════════════════════════════════
        # Step 9: 更新学科图谱
        # ═══════════════════════════════════════════════════
        logger.info("🔄 更新学科图谱...")
        
        discipline_manager.update_discipline_graph(discipline, book_graph)

        # ═══════════════════════════════════════════════════
        # Step 10: 输出处理报告
        # ═══════════════════════════════════════════════════
        elapsed_time = time.time() - start_time

        result["success"] = True
        result["discipline"] = discipline
        result["elapsed_time"] = elapsed_time
        result["chapter_count"] = len(parse_result.chapters)

        # Token 节省统计
        if wiki_enricher:
            tokens_saved = wiki_enricher.get_token_savings()
            result["tokens_saved"] = tokens_saved

        logger.info("="*60)
        logger.info(f"✅ 处理完成：{book_path.name}")
        logger.info(f"   学科：{discipline}")
        logger.info(f"   输出：{output_path}")
        logger.info(f"   耗时：{elapsed_time:.2f}秒")
        logger.info(f"   章节：{result['chapter_count']}")
        if wiki_enricher:
            logger.info(f"   💰 Token节省：{tokens_saved}")
        logger.info("="*60)
        
    except Exception as e:
        import traceback
        logger.error(f"❌ 处理失败：{e}")
        logger.error(f"   完整堆栈:")
        traceback.print_exc()
        result["error"] = str(e)
    
    # 标记为已处理
    if progress:
        if result["success"]:
            progress.mark_processed(book_path_str, result)
        else:
            progress.mark_failed(book_path_str, result.get("error", "未知错误"))
    
    return result


# ═══════════════════════════════════════════════════════════
# 批量处理
# ═══════════════════════════════════════════════════════════
def process_batch(
    directory: Path,
    config: Dict,
    discipline_override: str = None,
    max_workers: int = 1
) -> List[Dict]:
    """
    批量处理目录中的所有支持格式书籍
    
    - 递归扫描目录
    - 跳过已处理的书籍
    - 并发处理（最大 max_workers 个并发）
    - 生成批量处理报告
    """
    logger.info(f"📚 开始批量处理：{directory}（最大并发：{max_workers}）")
    
    # 初始化缓存和进度跟踪
    cache = Cache()
    progress = ProgressTracker()
    
    # 支持的格式
    supported_formats = config.get('parsing', {}).get('supported_formats', ['.epub', '.pdf', '.mobi'])
    
    # 扫描书籍文件
    book_files = []
    for ext in supported_formats:
        book_files.extend(directory.rglob(f"*{ext}"))
        book_files.extend(directory.rglob(f"*{ext.upper()}"))
    
    if not book_files:
        logger.warning(f"未找到支持的书籍文件：{supported_formats}")
        return []
    
    # 获取未处理的文件
    book_files_str = [str(f) for f in book_files]
    unprocessed = progress.get_unprocessed(book_files_str)
    skipped_count = len(book_files) - len(unprocessed)
    
    if skipped_count > 0:
        logger.info(f"⏭️  跳过已处理的 {skipped_count} 本书")
    
    if not unprocessed:
        logger.info("✅ 所有书籍已处理完成")
        return []
    
    logger.info(f"找到 {len(unprocessed)} 本待处理书籍")
    
    # 处理结果
    results = []
    successful = 0
    failed = 0
    
    start_time = time.time()
    
    # 使用 ThreadPoolExecutor 实现并发处理
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # 转换回 Path 对象
    unprocessed_paths = [Path(f) for f in unprocessed]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_book = {
            executor.submit(process_single_book, book_path, config, discipline_override, cache, progress): book_path
            for book_path in unprocessed_paths
        }
        
        # 处理完成的任务
        for i, future in enumerate(as_completed(future_to_book), 1):
            book_path = future_to_book[future]
            try:
                result = future.result()
                results.append(result)
                
                if result.get("skipped"):
                    skipped_count += 1
                    logger.info(f"[{i}/{len(unprocessed)}] ⏭️  {book_path.name}")
                elif result["success"]:
                    successful += 1
                    logger.info(f"[{i}/{len(unprocessed)}] ✅ {book_path.name}")
                else:
                    failed += 1
                    logger.info(f"[{i}/{len(unprocessed)}] ❌ {book_path.name}: {result['error']}")
                    
            except Exception as e:
                failed += 1
                logger.error(f"[{i}/{len(unprocessed)}] ❌ {book_path.name}: 异常 - {e}")
                results.append({
                    "success": False,
                    "book_path": str(book_path),
                    "error": str(e),
                })
    
    elapsed_time = time.time() - start_time
    
    # 输出批量处理报告
    logger.info("="*60)
    logger.info("📊 批量处理报告")
    logger.info("="*60)
    logger.info(f"总书籍数：{len(book_files)}")
    logger.info(f"✅ 成功：{successful}")
    logger.info(f"❌ 失败：{failed}")
    logger.info(f"⏭️  跳过：{skipped_count}")
    logger.info(f"⏱️  总耗时：{elapsed_time:.2f}秒")
    if successful > 0:
        logger.info(f"📈 平均速度：{elapsed_time / successful:.2f}秒/本")
    logger.info("="*60)
    
    return results


# ═══════════════════════════════════════════════════════════
# 命令行接口
# ═══════════════════════════════════════════════════════════
def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="BookGraph Agent - Obsidian 知识图谱生成系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --input book.pdf                    # 处理单本书
  python main.py --input ./books/                    # 批量处理目录
  python main.py --input book.pdf --discipline 哲学   # 指定学科
  python main.py --input book.pdf --verbose          # 详细输出

注意:
  LLM 通过 Hermes/Claude Code 工具调用，无需配置外部 API Key。
  运行时会输出 LLM 调用提示词，需要 Hermes/Claude Code 响应。
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="书籍文件路径或目录路径"
    )
    
    parser.add_argument(
        "--discipline", "-d",
        type=str,
        default=None,
        help="手动指定学科（可选）"
    )
    
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config.yaml",
        help="配置文件路径（默认：config.yaml）"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用详细输出"
    )
    
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="批量处理时的最大并发数（默认：1）"
    )
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 处理输入路径
    input_path = Path(args.input)
    
    if not input_path.exists():
        logger.error(f"输入路径不存在：{input_path}")
        sys.exit(1)
    
    if input_path.is_file():
        # 单本书处理
        result = process_single_book(input_path, config, args.discipline)
        
        if not result["success"]:
            logger.error(f"处理失败：{result['error']}")
            sys.exit(1)
    
    elif input_path.is_dir():
        # 批量处理
        results = process_batch(input_path, config, args.discipline, args.workers)
        
        if not results:
            logger.warning("没有处理任何书籍")
            sys.exit(0)
        
        # 检查是否有成功处理的
        successful = sum(1 for r in results if r["success"])
        if successful == 0:
            logger.error("所有书籍处理失败")
            sys.exit(1)
    
    logger.info("🎉 BookGraph Agent 完成")


if __name__ == "__main__":
    main()
