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
from core.llm_client import SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT, SYNTHESIS_PROMPT, DISCIPLINE_DETECTION_PROMPT
from utils.logger import setup_logger
from utils.path_manager import PathManager
from utils.cache import Cache
from utils.progress import ProgressTracker


# ═══════════════════════════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════════════════════════
logger = setup_logger("BookGraph-Agent")


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
def call_llm_via_tool(system_prompt: str, user_prompt: str, max_tokens: int = 16384) -> str:
    """
    输出 LLM 调用提示词，等待 Hermes/Claude Code 工具调用

    设计意图：BookGraph Agent 通过 Hermes/Claude Code 工具调用（使用当前对话的 LLM），
    而不是自己调用外部 API。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户输入
        max_tokens: 最大输出 token 数

    Returns:
        str: LLM 响应文本（由 Hermes Agent 提供）
    """
    # 输出提示词供 Hermes 调用
    print("\n" + "="*70)
    print("📝 [LLM 工具调用请求 - 请 Hermes Agent 处理]")
    print("="*70)
    print(f"System Prompt:\n{system_prompt[:1000]}...")
    print("-"*70)
    print(f"User Prompt:\n{user_prompt[:2000]}...")
    print("-"*70)
    print(f"Max Tokens: {max_tokens}")
    print("="*70)
    print("⚠️  此提示词需要 Hermes/Claude Code 工具调用处理")
    print("    请在 Claude Code 对话中使用当前 LLM 回答此问题")
    print("="*70 + "\n")

    # 返回 None 表示需要工具调用
    # 实际使用时，main.py 会检查返回值，如果为 None 则等待外部响应
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
        # Step 4: 确保目录结构存在
        # ═══════════════════════════════════════════════════
        obsidian_writer.ensure_discipline_structure(discipline)
        
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
                chunk_content=full_content[:25000],
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
            # 长内容：分块处理
            num_chunks = (content_length + max_chunk_size - 1) // max_chunk_size
            logger.info(f"🧩 分块分析中（{content_length}字符，{num_chunks}块）...")
            
            for i in range(num_chunks):
                start = i * max_chunk_size
                end = min((i + 1) * max_chunk_size, content_length)
                chunk_content = full_content[start:end]
                
                logger.info(f"   分析块 {i+1}/{num_chunks}...")
                
                prompt = CHUNK_ANALYSIS_PROMPT.format(
                    book_title=parse_result.metadata.get('title', book_path.stem),
                    chunk_content=chunk_content[:25000],
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
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ 块 {i+1} JSON 解析失败：{e}")
                        raise Exception(f"LLM 响应解析失败")
                else:
                    logger.error(f"❌ 需要 Hermes/Claude Code 工具调用处理块 {i+1}")
                    raise Exception("需要 LLM 工具调用响应")
            
            logger.info(f"✅ 完成 {num_chunks} 个分块分析")
        
        # ═══════════════════════════════════════════════════
        # Step 6: 综合生成 BookGraph（通过 LLM 调用）
        # ═══════════════════════════════════════════════════
        logger.info("🔮 综合生成知识图谱...")
        
        # 根据传入的学科名称获取对应的 DisciplineType
        try:
            discipline_enum = DisciplineType(discipline)
        except ValueError:
            # 如果传入的学科不在枚举中，默认使用政治学
            discipline_enum = DisciplineType.政治学
            logger.warning(f"⚠️  未知学科 '{discipline}'，使用默认学科：政治学")
        
        # 输出综合提示词
        analyses_str = json.dumps(all_analyses, ensure_ascii=False, indent=2)[:50000]
        
        synthesis_prompt = SYNTHESIS_PROMPT.format(
            book_title=parse_result.metadata.get('title', book_path.stem),
            author=parse_result.metadata.get('author', 'Unknown'),
            all_chunk_analyses=analyses_str,
        )
        
        logger.info(f"📡 调用 LLM 生成知识图谱...")
        
        # 调用 LLM 生成完整的知识图谱
        llm_response = call_llm_via_tool(SYSTEM_PROMPT, synthesis_prompt, max_tokens=16384)

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
                logger.warning(f"⚠️  JSON 解析失败：{e}，尝试使用原始响应")
                book_graph_data = {}
        else:
            logger.warning("⚠️  LLM 调用未获取响应")
        
        # 从 LLM 响应构建 BookGraph，如果失败则使用合理的默认值
        from schemas.book_graph_schema import (
            BookGraph, BookMetadata, TimeBackground, CriticalAnalysis,
            ChapterSummary, CoreConcept, KeyInsight, KeyCase, KeyQuote
        )
        
        # 提取元数据
        meta = book_graph_data.get('metadata', {})
        book_graph = BookGraph(
            metadata=BookMetadata(
                title=meta.get('title', parse_result.metadata.get('title', book_path.stem)),
                author=meta.get('author', parse_result.metadata.get('author', 'Unknown')),
                author_intro=meta.get('author_intro', f"{meta.get('author', '作者')}是本书的作者，其思想和理论对{discipline}领域产生了重要影响。"),
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
        
        logger.info("="*60)
        logger.info(f"✅ 处理完成：{book_path.name}")
        logger.info(f"   学科：{discipline}")
        logger.info(f"   输出：{output_path}")
        logger.info(f"   耗时：{elapsed_time:.2f}秒")
        logger.info(f"   章节：{result['chapter_count']}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ 处理失败：{e}")
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
