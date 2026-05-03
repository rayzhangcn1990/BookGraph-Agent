"""
并发协调器

协调多个 Skill 并发执行，实现：
- 并发处理（Semaphore 控制）
- 增量写入（每 Skill 完成即写入）
- 失败汇总（记录所有失败模块）
"""

import asyncio
import json
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.skills.base_skill import BaseSkill, SkillResult
from core.skills.chapter_skill import ChapterSkill
from core.skills.concept_skill import ConceptSkill
from core.skills.insight_skill import InsightSkill
from core.skills.case_skill import CaseSkill
from core.skills.quote_skill import QuoteSkill

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class BookProcessingResult:
    """书籍处理结果"""
    book_title: str
    total_skills: int
    successful_skills: int
    failed_skills: List[str]
    errors: Dict[str, List[str]]
    elapsed_seconds: float
    output_path: Optional[Path]


class SkillOrchestrator:
    """并发协调器"""

    def __init__(self, config: Dict):
        """
        初始化协调器

        Args:
            config: 配置字典
        """
        self.config = config
        self.max_parallel = config.get("batch", {}).get("skill_parallel", 4)

        # 初始化所有 Skill
        self.skills = [
            ChapterSkill(),
            ConceptSkill(),
            InsightSkill(),
            CaseSkill(),
            QuoteSkill(),
        ]

        logger.info(f"🎯 初始化 SkillOrchestrator: {len(self.skills)} 个 Skills")
        logger.info(f"   最大并发数: {self.max_parallel}")

    async def process_book(
        self,
        book_info: Dict,
        llm_client,
        obsidian_writer,
        discipline: str
    ) -> BookProcessingResult:
        """
        处理一本书

        Args:
            book_info: 书籍信息 (path, name, char_count)
            llm_client: LLM 客户端
            obsidian_writer: Obsidian 写入器
            discipline: 学科

        Returns:
            BookProcessingResult: 处理结果
        """
        import time
        start_time = time.time()

        book_title = book_info.get("name", "Unknown")
        book_path = book_info.get("path", "")

        logger.info("=" * 60)
        logger.info(f"📚 开始处理: {book_title}")
        logger.info("=" * 60)

        # Step 1: 解析书籍 → chunks
        chunks = await self._parse_book(book_path, book_title)

        if not chunks:
            logger.error(f"❌ 书籍解析失败: {book_title}")
            return BookProcessingResult(
                book_title=book_title,
                total_skills=len(self.skills),
                successful_skills=0,
                failed_skills=["parse"],
                errors={"parse": ["书籍解析失败"]},
                elapsed_seconds=0,
                output_path=None
            )

        logger.info(f"   📖 分块完成: {len(chunks)} 个 chunks")

        # Step 2: 创建 Obsidian 骨架文件
        self._create_skeleton(obsidian_writer, book_title, discipline)

        # Step 3: 并发执行所有 Skill
        semaphore = asyncio.Semaphore(self.max_parallel)

        # 🔑 总体超时控制（每本书最多10分钟）
        total_timeout = self.config.get("batch", {}).get("book_timeout", 600)

        async def run_skill(skill: BaseSkill) -> SkillResult:
            async with semaphore:
                logger.info(f"   ▶️ 开始执行: [{skill.name}]")
                try:
                    # 🔑 单个Skill超时（最多3分钟）
                    result = await asyncio.wait_for(
                        skill.run_and_write(
                            llm_client, chunks, book_title,
                            obsidian_writer, discipline
                        ),
                        timeout=180  # 3分钟超时
                    )
                    logger.info(f"   {'✅' if result.success else '❌'} 完成: [{skill.name}]")
                    return result
                except asyncio.TimeoutError:
                    logger.error(f"   ❌ [{skill.name}] 超时（180s）")
                    return SkillResult(
                        skill_name=skill.name,
                        success=False,
                        result=None,
                        errors=["Skill执行超时"],
                        elapsed_seconds=180
                    )

        # 并发执行（带总体超时）
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[run_skill(skill) for skill in self.skills],
                    return_exceptions=True
                ),
                timeout=total_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ 书籍处理总超时（{total_timeout}s）")
            # 返回部分结果
            results = []
            for skill in self.skills:
                results.append(SkillResult(
                    skill_name=skill.name,
                    success=False,
                    result=None,
                    errors=["总体超时"],
                    elapsed_seconds=total_timeout
                ))

        # Step 4: 汇总结果
        skill_results = []
        failed_skills = []
        errors = {}

        for i, result in enumerate(results):
            skill_name = self.skills[i].name

            if isinstance(result, Exception):
                failed_skills.append(skill_name)
                errors[skill_name] = [str(result)[:50]]
            elif isinstance(result, SkillResult):
                skill_results.append(result)
                if not result.success:
                    failed_skills.append(skill_name)
                    errors[skill_name] = result.errors
            else:
                failed_skills.append(skill_name)
                errors[skill_name] = ["未知结果类型"]

        # Step 5: 生成完整 BookGraph（汇总所有结果）
        output_path = await self._generate_final_book_graph(
            skill_results, book_title, discipline, obsidian_writer
        )

        elapsed = time.time() - start_time
        successful = len(self.skills) - len(failed_skills)

        logger.info("=" * 60)
        logger.info(f"📊 处理完成: {book_title}")
        logger.info(f"   ✅ 成功: {successful}/{len(self.skills)}")
        if failed_skills:
            logger.info(f"   ❌ 失败: {failed_skills}")
        logger.info(f"   ⏱️ 耗时: {elapsed:.1f}s")
        logger.info("=" * 60)

        return BookProcessingResult(
            book_title=book_title,
            total_skills=len(self.skills),
            successful_skills=successful,
            failed_skills=failed_skills,
            errors=errors,
            elapsed_seconds=elapsed,
            output_path=output_path
        )

    async def process_books_batch(
        self,
        book_infos: List[Dict],
        llm_client,
        obsidian_writer,
        discipline: str
    ) -> List[BookProcessingResult]:
        """
        批量处理多本书

        Args:
            book_infos: 书籍信息列表
            llm_client: LLM 客户端
            obsidian_writer: Obsidian 写入器
            discipline: 学科

        Returns:
            List[BookProcessingResult]: 所有处理结果
        """
        results = []

        # 逐本处理（每本内部并发）
        for i, book_info in enumerate(book_infos, 1):
            logger.info(f"\n[{i}/{len(book_infos)}] 处理书籍...")

            result = await self.process_book(
                book_info, llm_client, obsidian_writer, discipline
            )
            results.append(result)

        # 打印摘要
        self._print_batch_summary(results)

        return results

    # ═══════════════════════════════════════════════════════════
    # 私有方法
    # ═══════════════════════════════════════════════════════════

    async def _parse_book(self, book_path: str, book_title: str) -> List[Tuple[int, str, str]]:
        """解析书籍，生成 chunks"""
        try:
            from main import BookParser

            parsing_config = self.config.get("parsing", {})
            parser = BookParser(book_path, parsing_config)
            parse_result = parser.parse()

            if not parse_result.success:
                logger.error(f"解析失败: {parse_result.error}")
                return []

            # 分块
            chunks = []
            max_chunk_size = self.config.get("llm", {}).get("chunk_size", 30000)

            for i, chapter in enumerate(parse_result.chapters):
                content = chapter.get("content", "")
                title = chapter.get("title", f"第{i+1}章")

                if len(content) <= max_chunk_size:
                    chunks.append((len(chunks), content, title))
                else:
                    # 大章节拆分
                    for j in range(0, len(content), max_chunk_size):
                        sub_content = content[j:j+max_chunk_size]
                        chunks.append((
                            len(chunks),
                            sub_content,
                            f"{title} - 部分{j//max_chunk_size+1}"
                        ))

            return chunks

        except Exception as e:
            logger.error(f"解析异常: {e}")
            return []

    def _create_skeleton(self, obsidian_writer, book_title: str, discipline: str):
        """创建 Obsidian 骨架文件"""
        from datetime import datetime

        skeleton = f"""---
title: {book_title}
author: 未知作者
discipline: {discipline}
year_published: null
tags: []
category: []
related_books: []
created: {datetime.now().strftime('%Y-%m-%d')}
type: book-graph
---

## 📑 章节结构总览

> [!info] 正在生成...

---

## 💡 核心概念

> [!info] 正在生成...

---

## 🔍 关键洞见

> [!info] 正在生成...

---

## 📚 关键案例

> [!info] 正在生成...

---

## ✨ 金句萃取

> [!info] 正在生成...

---

*最后更新*: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""

        # 写入骨架
        try:
            # 使用 write_book_graph 需要一个 BookGraph 对象，简化处理
            from pathlib import Path
            discipline_path = self._get_discipline_path(discipline)
            books_dir = Path(obsidian_writer.vault_path) / discipline_path / "书籍图谱"
            books_dir.mkdir(parents=True, exist_ok=True)

            safe_title = self._sanitize_filename(book_title)
            file_path = books_dir / f"{safe_title}.md"

            # 如果已存在，先删除
            if file_path.exists():
                file_path.unlink()

            file_path.write_text(skeleton, encoding="utf-8")
            logger.info(f"   📝 创建骨架: {file_path.name}")

        except Exception as e:
            logger.warning(f"创建骨架失败: {e}")

    async def _generate_final_book_graph(
        self,
        skill_results: List[SkillResult],
        book_title: str,
        discipline: str,
        obsidian_writer
    ) -> Optional[Path]:
        """汇总所有 Skill 结果，生成最终 BookGraph"""

        # 合并所有结果
        merged_data = {
            "metadata": {
                "title": book_title,
                "author": "未知作者",
                "author_intro": "",
                "discipline": discipline,
                "year_published": None,
                "category": [],
                "tags": [],
                "related_books": []
            },
            "time_background": {
                "macro_background": "",
                "micro_background": "",
                "core_contradiction": ""
            },
            "chapter_summaries": [],
            "core_concepts": [],
            "key_insights": [],
            "key_cases": [],
            "key_quotes": [],
            "critical_analysis": {
                "core_doubts": [],
                "feminist_perspective": "",
                "postcolonial_perspective": "",
                "ethical_boundaries": {}
            },
            "learning_path": {},
            "book_network": {}
        }

        # 合并各 Skill 结果
        for result in skill_results:
            if result.success and result.result:
                field_mapping = {
                    "chapter": "chapter_summaries",
                    "concept": "core_concepts",
                    "insight": "key_insights",
                    "case": "key_cases",
                    "quote": "key_quotes"
                }

                field = field_mapping.get(result.skill_name)
                if field and field in result.result:
                    merged_data[field] = result.result[field]

        # 构建 BookGraph 对象
        try:
            from schemas.book_graph_schema import (
                BookGraph, BookMetadata, TimeBackground, CriticalAnalysis,
                DisciplineType, ChapterSummary, CoreConcept, KeyInsight,
                KeyCase, KeyQuote
            )

            # 处理 discipline 类型
            disc_value = merged_data["metadata"]["discipline"]
            try:
                disc_enum = DisciplineType(disc_value)
            except ValueError:
                disc_enum = DisciplineType.哲学

            metadata = BookMetadata(
                title=merged_data["metadata"]["title"],
                author=merged_data["metadata"]["author"],
                author_intro=merged_data["metadata"]["author_intro"],
                discipline=disc_enum,
                year_published=merged_data["metadata"]["year_published"],
                category=merged_data["metadata"]["category"],
                tags=merged_data["metadata"]["tags"],
                related_books=merged_data["metadata"]["related_books"]
            )

            time_bg = TimeBackground(
                macro_background=merged_data["time_background"]["macro_background"],
                micro_background=merged_data["time_background"]["micro_background"],
                core_contradiction=merged_data["time_background"]["core_contradiction"]
            )

            # 构建 chapters
            chapters = []
            for ch in merged_data.get("chapter_summaries", []):
                chapters.append(ChapterSummary(
                    chapter_number=str(ch.get("chapter_number", "?")),
                    title=ch.get("title", ""),
                    core_argument=ch.get("core_argument", ""),
                    underlying_logic=ch.get("underlying_logic", ""),
                    related_books=ch.get("related_books", []),
                    critical_questions=ch.get("critical_questions", [])
                ))

            # 构建 concepts
            concepts = []
            for c in merged_data.get("core_concepts", []):
                concepts.append(CoreConcept(
                    name=c.get("name", ""),
                    definition=c.get("definition", ""),
                    deep_meaning=c.get("deep_meaning", ""),
                    underlying_logic=c.get("underlying_logic", ""),
                    development_stages=c.get("development_stages", []),
                    core_drivers=c.get("core_drivers", []),
                    critical_review=c.get("critical_review", ""),
                    related_books=c.get("related_books", [])
                ))

            # 构建 insights
            insights = []
            for ins in merged_data.get("key_insights", []):
                insights.append(KeyInsight(
                    title=ins.get("title", ""),
                    description=ins.get("description", ""),
                    underlying_logic=ins.get("underlying_logic", ""),
                    deep_assumptions=ins.get("deep_assumptions", []),
                    related_books=ins.get("related_books", []),
                    controversies=ins.get("controversies", ""),
                    multi_perspectives=ins.get("multi_perspectives", {})
                ))

            # 构建 cases
            cases = []
            for cas in merged_data.get("key_cases", []):
                cases.append(KeyCase(
                    name=cas.get("name", ""),
                    source_chapter=cas.get("source_chapter", ""),
                    event_description=cas.get("event_description", ""),
                    development_stages=cas.get("development_stages", []),
                    core_drivers=cas.get("core_drivers", []),
                    related_books=cas.get("related_books", []),
                    historical_limitations=cas.get("historical_limitations", "")
                ))

            # 构建 quotes
            quotes = []
            for q in merged_data.get("key_quotes", []):
                quotes.append(KeyQuote(
                    text=q.get("text", ""),
                    chapter=q.get("chapter", ""),
                    core_theme=q.get("core_theme", ""),
                    background_context=q.get("background_context", ""),
                    underlying_logic=q.get("underlying_logic", ""),
                    common_misreading=q.get("common_misreading"),
                    related_books=q.get("related_books", [])
                ))

            critical = CriticalAnalysis(
                core_doubts=merged_data["critical_analysis"]["core_doubts"],
                feminist_perspective=merged_data["critical_analysis"]["feminist_perspective"],
                postcolonial_perspective=merged_data["critical_analysis"]["postcolonial_perspective"],
                ethical_boundaries=merged_data["critical_analysis"]["ethical_boundaries"]
            )

            book_graph = BookGraph(
                metadata=metadata,
                time_background=time_bg,
                chapters=chapters,
                core_concepts=concepts,
                key_insights=insights,
                key_cases=cases,
                key_quotes=quotes,
                critical_analysis=critical,
                learning_path=merged_data["learning_path"],
                book_network=merged_data["book_network"]
            )

            # 生成 Markdown 并写入
            from core.graph_generator import GraphGenerator
            generator = GraphGenerator(self.config)
            markdown = generator.generate_book_graph_markdown(book_graph)

            output_path = obsidian_writer.write_book_graph(book_graph, markdown)

            return output_path

        except Exception as e:
            logger.error(f"生成最终 BookGraph 失败: {e}")
            return None

    def _get_discipline_path(self, discipline: str) -> str:
        """获取学科路径"""
        discipline_paths = self.config.get("obsidian", {}).get("discipline_paths", {})
        if discipline in discipline_paths:
            return discipline_paths[discipline]
        return f"📚 知识图谱/{discipline}"

    def _sanitize_filename(self, name: str) -> str:
        """生成安全文件名"""
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            name = name.replace(char, '_')
        return name.strip()[:100]

    def _print_batch_summary(self, results: List[BookProcessingResult]):
        """打印批量处理摘要"""
        print("\n" + "=" * 60)
        print("📊 批量处理摘要")
        print("=" * 60)

        total = len(results)
        success = sum(1 for r in results if r.successful_skills == r.total_skills)
        partial = sum(1 for r in results if 0 < r.successful_skills < r.total_skills)
        failed = sum(1 for r in results if r.successful_skills == 0)

        print(f"\n总计: {total} 本")
        print(f"  ✅ 完全成功: {success} 本")
        print(f"  ⚠️ 部分成功: {partial} 本")
        print(f"  ❌ 全部失败: {failed} 本")

        if partial > 0:
            print("\n部分成功书籍详情:")
            for r in results:
                if 0 < r.successful_skills < r.total_skills:
                    print(f"  - {r.book_title}: {r.successful_skills}/{r.total_skills}")
                    print(f"    失败模块: {r.failed_skills}")

        print("=" * 60)