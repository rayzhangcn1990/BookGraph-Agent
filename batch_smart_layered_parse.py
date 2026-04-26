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
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)m | %(message)s')
logger = logging.getLogger("SmartBatchParser")

from main import BookParser, process_single_book, ObsidianWriter
from core.multi_model_chunk_processor import MultiModelChunkProcessor
from core.llm_client import SYNTHESIS_PROMPT, SYSTEM_PROMPT, CHUNK_ANALYSIS_PROMPT
import httpx


# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

SHORT_BOOK_THRESHOLD = 50000  # 字符数阈值
MAX_SHORT_BOOKS_PARALLEL = 8  # 短书最大并行数
MAX_LONG_BOOK_MODELS = 4      # 长书最大并行模型数


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
    """处理短书（单模型，多书并行）"""
    async with semaphore:
        book_info.status = "running"
        start_time = datetime.now()

        logger.info(f"📚 [短书] 开始: {book_info.name}")

        try:
            # 使用现有的 process_single_book（单模型串行）
            result = await asyncio.to_thread(
                process_single_book,
                Path(book_info.path),
                config,
                discipline
            )

            book_info.result = result
            book_info.status = "completed"

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ [短书] 完成: {book_info.name} ({duration:.1f}s)")

        except Exception as e:
            book_info.status = "failed"
            book_info.result = {"error": str(e)}
            logger.error(f"❌ [短书] 失败: {book_info.name} - {str(e)[:100]}")

        return book_info


# ═══════════════════════════════════════════════════════════
# 长书处理（多模型分块并行，单书独占）
# ═══════════════════════════════════════════════════════════

async def process_long_book(
    book_info: BookInfo,
    config: Dict,
    discipline: str
) -> BookInfo:
    """处理长书（多模型分块并行，独占资源）"""
    book_info.status = "running"
    start_time = datetime.now()

    logger.info("=" * 60)
    logger.info(f"📚 [长书] 开始: {book_info.name} ({book_info.char_count} 字符)")
    logger.info("=" * 60)
    logger.info(f"   策略: 多模型分块并行，独占处理")

    try:
        # 1. 解析书籍
        book_parser = BookParser(book_info.path, config.get("parsing", {}))
        parse_result = book_parser.parse()

        if not parse_result.success:
            raise Exception(f"书籍解析失败: {parse_result.error}")

        # 2. 分块
        chunks = []
        max_chunk_size = config.get("llm", {}).get("chunk_size", 30000)

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

        # 3. 多模型分块并行处理
        processor = MultiModelChunkProcessor(config, MAX_LONG_BOOK_MODELS)

        tasks = await processor.process_book_chunks_parallel(
            chunks,
            parse_result.metadata.get("title", book_info.name),
            SYSTEM_PROMPT,
            CHUNK_ANALYSIS_PROMPT
        )

        processor.print_summary(tasks)

        # 4. 合并结果
        all_analyses = [t.result for t in tasks if t.status == "completed" and t.result]

        if not all_analyses:
            raise Exception("没有成功的 chunk 分析结果")

        # 5. 综合分析
        synthesis = await synthesize_results(
            all_analyses,
            parse_result.metadata.get("title", book_info.name),
            parse_result.metadata,
            discipline,
            config
        )

        # 6. 写入 Obsidian（使用正确的接口）
        obsidian_writer = ObsidianWriter(config.get("obsidian", {}))

        # 生成 Markdown
        from core.graph_generator import GraphGenerator
        graph_generator = GraphGenerator(config)
        markdown_content = graph_generator.generate_book_graph_markdown(synthesis)

        # 写入文件
        output_path = obsidian_writer.write_book_graph(synthesis, markdown_content)

        book_info.result = {
            "output_path": str(output_path),
            "chunks_processed": len([t for t in tasks if t.status == "completed"]),
            "chunks_failed": len([t for t in tasks if t.status == "failed"]),
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
    """使用最佳模型综合分析结果"""

    llm_config = config.get("llm", {})
    api_sources = llm_config.get("api_sources", [])

    # 选择最佳 API 源
    api_source = None
    for source in api_sources:
        if "openrouter" in source.get("name", "").lower() and "main" in source.get("name", "").lower():
            api_source = source
            break

    if not api_source:
        for source in api_sources:
            if "openrouter" in source.get("name", "").lower():
                api_source = source
                break

    if not api_source and api_sources:
        api_source = api_sources[0]

    if not api_source:
        raise Exception("没有可用的 API 源")

    api_base = api_source["api_base"]
    api_key = api_source["api_key"]
    model = "claude-sonnet-4.6"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    if "openrouter" in api_source.get("name", "").lower():
        headers["HTTP-Referer"] = "https://bookgraph.app"
        headers["X-Title"] = "BookGraph-Agent"

    analyses_json = json.dumps(all_analyses, ensure_ascii=False, indent=2)[:50000]

    # 🔑 修复：使用正确的 prompt 格式参数（与 llm_client.py 一致）
    prompt = SYNTHESIS_PROMPT.format(
        book_title=book_title,
        author=metadata.get('author', 'Unknown'),  # 🔑 添加缺失的 author 参数
        chapters_list="",  # 暂时留空，后续可优化
        all_chunk_analyses=analyses_json,
    )

    logger.info(f"   🧠 综合分析中... (使用 {model})")

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{api_base.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是一位政治学知识图谱专家。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 32768,
                "temperature": 0.7
            }
        )

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            try:
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = content[json_start:json_end]
                else:
                    json_str = content

                return json.loads(json_str)

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败: {e}")
                raise Exception(f"综合分析 JSON 解析失败: {e}")

        else:
            raise Exception(f"综合分析失败: HTTP {response.status_code}")


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

        # 2. 长书逐本独占处理
        if self.long_books:
            logger.info("\n" + "=" * 60)
            logger.info(f"📚 长书独占处理 ({len(self.long_books)} 本)")
            logger.info(f"   每本最大并行模型: {MAX_LONG_BOOK_MODELS}")
            logger.info("=" * 60)

            for i, book in enumerate(self.long_books, 1):
                logger.info(f"\n[{i}/{len(self.long_books)}] 处理长书...")

                result = await process_long_book(book, self.config, self.discipline)

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
        long_failed = [r for r in results if r.is_long and r.status == "failed"]

        print(f"\n短书处理:")
        print(f"  ✅ 完成: {len(short_completed)} 本")
        print(f"  ❌ 失败: {len(short_failed)} 本")

        print(f"\n长书处理:")
        print(f"  ✅ 完成: {len(long_completed)} 本")
        print(f"  ❌ 失败: {len(long_failed)} 本")

        print(f"\n总计:")
        print(f"  ✅ 完成: {len(short_completed) + len(long_completed)} 本")
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