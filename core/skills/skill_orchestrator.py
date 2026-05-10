"""
并发协调器

协调多个 Skill 并发执行，实现：
- 并发处理（Semaphore 控制）
- 增量写入（每 Skill 完成即写入）
- 失败汇总（记录所有失败模块）
- 🔑 Per-Skill 质量检查（PUA 标准：每 Skill 完成即校验）
"""

import asyncio
import json
import logging
import re
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
from core.skills.background_skill import BackgroundSkill
from core.skills.critical_skill import CriticalSkill

# 🔑 新增：Per-Skill 质量检查
from core.book_graph_quality_checker import check_skill_output

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
            BackgroundSkill(),  # 时代背景（优先执行，填充 Wikipedia 信息）
            ChapterSkill(),
            ConceptSkill(),
            InsightSkill(),
            CaseSkill(),
            QuoteSkill(),
            CriticalSkill(),    # 批判性分析（最后执行）
        ]

        logger.info(f"🎯 初始化 SkillOrchestrator: {len(self.skills)} 个 Skills")
        logger.info(f"   最大并发数: {self.max_parallel}")

    async def process_book(
        self,
        book_info: Dict,
        llm_client,
        obsidian_writer,
        discipline: str,
        extraction_passes: int = 1  # 🆕 新增参数
    ) -> BookProcessingResult:
        """
        处理一本书

        🆕 改造：支持多轮提取（提高召回率）

        Args:
            book_info: 书籍信息 (path, name, char_count)
            llm_client: LLM 客户端
            obsidian_writer: Obsidian 写入器
            discipline: 学科
            extraction_passes: 提取轮数（默认 1，建议 1-3）

        Returns:
            BookProcessingResult: 处理结果
        """
        import time
        start_time = time.time()

        book_title = book_info.get("name", "Unknown")
        book_path = book_info.get("path", "")

        # 🆕 从配置读取 extraction_passes
        if extraction_passes == 1:
            extraction_passes = self.config.get("extraction", {}).get("passes", 1)

        logger.info("=" * 60)
        logger.info(f"📚 开始处理: {book_title}")
        if extraction_passes > 1:
            logger.info(f"   🔄 多轮提取模式: {extraction_passes} 轮")
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

        # 🆕 Step 3: 多轮提取
        all_pass_results = []  # 存储每轮结果

        for pass_num in range(1, extraction_passes + 1):
            if extraction_passes > 1:
                logger.info(f"\n   🔄 第 {pass_num}/{extraction_passes} 轮提取...")

            # 并发执行所有 Skill
            pass_results = await self._run_skills_parallel(
                chunks, book_title, llm_client, obsidian_writer, discipline
            )
            all_pass_results.append(pass_results)

        # 🆕 Step 4: 合并多轮结果
        if extraction_passes > 1:
            merged_results = self._merge_multi_pass_results(all_pass_results)
        else:
            merged_results = all_pass_results[0] if all_pass_results else []

        # Step 5: 汇总结果
        skill_results = []
        failed_skills = []
        errors = {}

        for i, result in enumerate(merged_results):
            skill_name = self.skills[i].name if i < len(self.skills) else f"Skill-{i}"

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

        # Step 6: 生成完整 BookGraph
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

    async def _run_skills_parallel(
        self,
        chunks: List[Dict],
        book_title: str,
        llm_client,
        obsidian_writer,
        discipline: str
    ) -> List[SkillResult]:
        """
        并发执行所有 Skill（单轮）

        Args:
            chunks: chunk 列表
            book_title: 书名
            llm_client: LLM 客户端
            obsidian_writer: Obsidian 写入器
            discipline: 学科

        Returns:
            List[SkillResult]: 本轮所有 Skill 结果
        """
        semaphore = asyncio.Semaphore(self.max_parallel)
        total_timeout = self.config.get("batch", {}).get("book_timeout", 600)

        async def run_skill(skill: BaseSkill) -> SkillResult:
            async with semaphore:
                logger.info(f"   ▶️ 开始执行: [{skill.name}]")
                try:
                    result = await asyncio.wait_for(
                        skill.run_and_write(
                            llm_client, chunks, book_title,
                            obsidian_writer, discipline
                        ),
                        timeout=180
                    )

                    # 🔑 Per-Skill 质量检查（PUA 标准）
                    if result.success and result.result:
                        quality_passed, quality_msg = check_skill_output(skill.name, result.result)
                        if not quality_passed:
                            logger.warning(f"   ⚠️ [{skill.name}] 质量不合格: {quality_msg}")
                            # 标记质量问题但不影响 success 状态（仅警告）
                            result.quality_warning = quality_msg
                        else:
                            logger.info(f"   ✅ [{skill.name}] 质量检查通过")

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

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[run_skill(skill) for skill in self.skills],
                    return_exceptions=True
                ),
                timeout=total_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ 本轮超时（{total_timeout}s）")
            results = []
            for skill in self.skills:
                results.append(SkillResult(
                    skill_name=skill.name,
                    success=False,
                    result=None,
                    errors=["本轮超时"],
                    elapsed_seconds=total_timeout
                ))

        return results

    def _merge_multi_pass_results(
        self,
        all_pass_results: List[List[SkillResult]]
    ) -> List[SkillResult]:
        """
        合并多轮提取结果

        策略：第一轮优先，后续轮只添加不重叠的 Extraction

        Args:
            all_pass_results: 每轮的结果列表

        Returns:
            List[SkillResult]: 合并后的结果
        """
        if not all_pass_results:
            return []

        if len(all_pass_results) == 1:
            return all_pass_results[0]

        # 以第一轮为基准
        merged = list(all_pass_results[0])

        # 遍历后续轮
        for pass_idx, pass_results in enumerate(all_pass_results[1:], 2):
            logger.info(f"   🔀 合并第 {pass_idx} 轮结果...")

            for skill_idx, result in enumerate(pass_results):
                if skill_idx >= len(merged):
                    merged.append(result)
                    continue

                merged_result = merged[skill_idx]

                # 合并 Extraction
                if isinstance(result, SkillResult) and isinstance(merged_result, SkillResult):
                    merged_extractions = merged_result.extractions or []
                    new_extractions = result.extractions or []

                    # 只添加不重叠的
                    for new_ext in new_extractions:
                        if new_ext.char_interval:
                            overlaps = False
                            for existing_ext in merged_extractions:
                                if existing_ext.char_interval and new_ext.char_interval.overlaps(existing_ext.char_interval):
                                    overlaps = True
                                    break

                            if not overlaps:
                                merged_extractions.append(new_ext)

                    merged[skill_idx] = SkillResult(
                        skill_name=merged_result.skill_name,
                        success=merged_result.success or result.success,
                        result=merged_result.result,  # JSON 结果保持第一轮
                        errors=merged_result.errors,
                        extractions=merged_extractions,
                        elapsed_seconds=merged_result.elapsed_seconds + result.elapsed_seconds
                    )

        # 打印合并统计
        for i, result in enumerate(merged):
            if isinstance(result, SkillResult) and result.extractions:
                logger.info(f"   📊 [{result.skill_name}] 合并后: {len(result.extractions)} 条提取")

        return merged

    async def process_books_batch(
        self,
        book_infos: List[Dict],
        llm_client,
        obsidian_writer,
        discipline: str,
        extraction_passes: int = 1  # 🆕 新增参数
    ) -> List[BookProcessingResult]:
        """
        批量处理多本书

        🆕 改造：支持多轮提取

        Args:
            book_infos: 书籍信息列表
            llm_client: LLM 客户端
            obsidian_writer: Obsidian 写入器
            discipline: 学科
            extraction_passes: 提取轮数（默认 1）

        Returns:
            List[BookProcessingResult]: 所有处理结果
        """
        results = []

        # 🆕 从配置读取 extraction_passes
        if extraction_passes == 1:
            extraction_passes = self.config.get("extraction", {}).get("passes", 1)

        # 逐本处理（每本内部并发）
        for i, book_info in enumerate(book_infos, 1):
            logger.info(f"\n[{i}/{len(book_infos)}] 处理书籍...")

            # 🆕 传递 extraction_passes
            result = await self.process_book(
                book_info, llm_client, obsidian_writer, discipline,
                extraction_passes=extraction_passes
            )
            results.append(result)

        # 打印摘要
        self._print_batch_summary(results)

        return results

    # ═══════════════════════════════════════════════════════════
    # 私有方法
    # ═══════════════════════════════════════════════════════════

    async def _parse_book(self, book_path: str, book_title: str) -> List[Dict]:
        """
        解析书籍，生成 chunks

        🆕 改造：返回带位置信息的 chunks，每个 chunk 包含：
            - chunk_index: 序号
            - content: 内容
            - label: 标签（章节标题）
            - char_interval: {start_pos, end_pos} 在原文中的位置
            - source_text: 完整原文（用于对齐）

        Returns:
            List[Dict]: chunks 列表
        """
        try:
            from main import BookParser

            parsing_config = self.config.get("parsing", {})
            parser = BookParser(book_path, parsing_config)
            parse_result = parser.parse()

            if not parse_result.success:
                logger.error(f"解析失败: {parse_result.error}")
                return []

            # 🆕 合并所有章节内容，保存完整原文
            full_content = ""
            chapter_positions = []
            current_pos = 0

            for i, chapter in enumerate(parse_result.chapters):
                content = chapter.get("content", "")
                title = chapter.get("title", f"第{i+1}章")

                # 记录章节位置
                chapter_positions.append({
                    "chapter_index": i,
                    "title": title,
                    "start_pos": current_pos,
                    "end_pos": current_pos + len(content)
                })

                full_content += content
                current_pos += len(content)

            # 分块（带位置信息）
            chunks = []
            max_chunk_size = self.config.get("llm", {}).get("chunk_size", 30000)

            for i, chapter in enumerate(parse_result.chapters):
                content = chapter.get("content", "")
                title = chapter.get("title", f"第{i+1}章")
                chapter_start = chapter_positions[i]["start_pos"]

                if len(content) <= max_chunk_size:
                    chunks.append({
                        "chunk_index": len(chunks),
                        "content": content,
                        "label": title,
                        "char_interval": {
                            "start_pos": chapter_start,
                            "end_pos": chapter_start + len(content)
                        },
                        "source_text": full_content  # 🆕 传递完整原文
                    })
                else:
                    # 大章节拆分
                    for j in range(0, len(content), max_chunk_size):
                        sub_content = content[j:j+max_chunk_size]
                        chunks.append({
                            "chunk_index": len(chunks),
                            "content": sub_content,
                            "label": f"{title} - 部分{j//max_chunk_size+1}",
                            "char_interval": {
                                "start_pos": chapter_start + j,
                                "end_pos": chapter_start + j + len(sub_content)
                            },
                            "source_text": full_content  # 🆕 传递完整原文
                        })

            logger.info(f"   📖 完整原文长度: {len(full_content)} 字符")
            return chunks

        except Exception as e:
            logger.error(f"解析异常: {e}")
            return []

    def _create_skeleton(self, obsidian_writer, book_title: str, discipline: str, author: str = None):
        """创建 Obsidian 骨架文件（集成 Wikipedia 信息）"""
        from datetime import datetime

        # 🔑 使用 Wikipedia 获取作者信息和时代背景
        author_intro = ""
        time_background = ""

        try:
            from utils.wikipedia_enricher import WikipediaEnricher
            wiki = WikipediaEnricher()

            # 1. 先用书名搜索书籍 Wikipedia 页面（可能包含作者信息）
            book_page = wiki.wiki.page(book_title.replace('.epub', '').replace('.mobi', '').replace('.pdf', ''))
            if book_page.exists():
                # 从书籍页面提取作者信息
                book_summary = book_page.summary[:500]
                # 尝试提取作者名称
                if "作者" in book_summary or "作者" in book_summary:
                    import re
                    author_match = re.search(r'作者是?[:：]?([^，。,\n]+)', book_summary)
                    if author_match:
                        author = author_match.group(1).strip()
                        logger.info(f"   📚 Wikipedia 提取作者: {author}")

            # 2. 如果有作者名称，搜索作者 Wikipedia 页面
            if author and author != "未知作者":
                author_intro = wiki.search_author(author) or ""

            # 3. 尝试从书籍页面获取时代背景
            if book_page.exists():
                # 搜索书籍出版年代相关的事件
                # 提取年份信息
                import re
                years = re.findall(r'\b(19\d{2}|20\d{2})\b', book_summary)
                if years:
                    # 用第一个年份搜索历史背景
                    year_event = wiki.search_event(f"{years[0]}年")
                    if year_event:
                        time_background = year_event

        except Exception as e:
            logger.warning(f"   ⚠️ Wikipedia 查询失败: {e}")

        # 构建骨架（包含 Wikipedia 信息 + 强化视觉区分）
        skeleton = f"""---
title: {book_title}
author: {author or "未知作者"}
discipline: {discipline}
year_published: null
tags: []
category: []
related_books: []
created: {datetime.now().strftime('%Y-%m-%d')}
type: book-graph
---

# 📖 {book_title}

> [!info] ✍️ 作者简介
> {author_intro or "待补充"}

---

# 📜 一、时代背景

> [!quote] 🌍 宏观历史背景
> {time_background or "待补充"}

> [!note] 🔬 微观作者背景
> 待补充

### ⚡ 核心矛盾

待补充

---

# 📑 二、章节结构总览

> [!info] 正在生成...

---

# 💡 三、核心概念

> [!info] 正在生成...

---

# 🔍 四、关键洞见

> [!info] 正在生成...

---

# 📚 五、关键案例

> [!info] 正在生成...

---

# ✨ 六、金句萃取

> [!info] 正在生成...

---

# 🤔 七、批判性解读

> [!info] 待补充

---

# ⚖️ 八、伦理边界

> [!info] 待补充

---

# 📖 九、学习路径

> [!info] 待补充

---

# 🔗 十、关联书籍网络

> [!info] 待补充

---

*所属学科*: [[{discipline}学科图谱]]
*最后更新*: {datetime.now().strftime('%Y-%m-%d %H:%M')}
*图谱类型*: 书籍知识图谱"""

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
            "golden_quotes": [],  # 🔑 使用规范化的字段名
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
                    "background": "time_background",
                    "chapter": "chapter_summaries",
                    "concept": "core_concepts",
                    "insight": "key_insights",
                    "case": "key_cases",
                    "quote": "golden_quotes",  # 🔑 使用规范化的字段名
                    "critical": "critical_analysis"
                }

                field = field_mapping.get(result.skill_name)
                if field and field in result.result:
                    merged_data[field] = result.result[field]

        # ═══════════════════════════════════════════════════════════
        # 🔧 后处理：提取作者、聚合关联书籍、生成学习路径
        # ═══════════════════════════════════════════════════════════

        # 1️⃣ 提取作者信息（从 background skill）
        for result in skill_results:
            if result.skill_name == "background" and result.result:
                bg_data = result.result.get("time_background", {})
                # 提取作者姓名（从微观背景开头）
                # 格式1: "作者XXX（英文名）是..."
                # 格式2: "作者XXX是..."
                micro = bg_data.get("micro_background", "")
                author_match = re.search(r'作者([^（]+?)(?:（[^）]+）)?[是为]', micro)
                if author_match:
                    merged_data["metadata"]["author"] = author_match.group(1).strip()
                    logger.info(f"   ✅ 提取作者: {merged_data['metadata']['author']}")

                # 提取作者简介
                author_intro = result.result.get("author_intro", "")
                if author_intro and len(author_intro) > 20:
                    merged_data["metadata"]["author_intro"] = author_intro

        # 2️⃣ 聚合关联书籍（从所有 Skill 的 related_books）
        book_network = {}
        for result in skill_results:
            if result.success and result.result:
                # 遍历 result 中的所有列表字段
                for field_name, field_value in result.result.items():
                    if isinstance(field_value, list):
                        for item in field_value:
                            if isinstance(item, dict):
                                related = item.get("related_books", [])
                                # 处理字符串格式
                                if isinstance(related, str):
                                    related = [b.strip() for b in related.replace("，", ",").split(",") if b.strip()]
                                # 处理列表格式
                                if isinstance(related, list):
                                    for book in related:
                                        if book and book not in book_network:
                                            book_network[book] = f"在{result.skill_name}中被提及"
                                        elif book:
                                            # 多次提及，追加来源
                                            if result.skill_name not in book_network[book]:
                                                book_network[book] += f", {result.skill_name}"

        merged_data["book_network"] = book_network
        if book_network:
            logger.info(f"   ✅ 聚合关联书籍: {len(book_network)} 本")

        # 3️⃣ 生成学习路径（基于章节和概念）
        learning_path = {
            "beginner": [],
            "intermediate": [],
            "advanced": [],
            "practice": []
        }

        # 初学者：按章节顺序
        chapters = merged_data.get("chapter_summaries", [])
        if chapters:
            for ch in chapters[:3]:
                title = ch.get("title", "")
                if title:
                    learning_path["beginner"].append(f"阅读「{title}」，理解基础概念")

        # 进阶：核心概念深化
        concepts = merged_data.get("core_concepts", [])
        if concepts:
            for c in concepts[:3]:
                name = c.get("name", "")
                if name:
                    learning_path["intermediate"].append(f"深入理解「{name}」的定义与底层逻辑")

        # 深度研究：关键洞见批判
        insights = merged_data.get("key_insights", [])
        if insights:
            for ins in insights[:2]:
                title = ins.get("title", "")
                if title:
                    learning_path["advanced"].append(f"批判性审视「{title}」的多维视角")

        # 实践应用：案例迁移
        cases = merged_data.get("key_cases", [])
        if cases:
            for cas in cases[:2]:
                name = cas.get("name", "")
                if name:
                    learning_path["practice"].append(f"分析「{name}」案例，迁移应用经验")

        merged_data["learning_path"] = learning_path
        if any(learning_path.values()):
            logger.info(f"   ✅ 生成学习路径: {sum(len(v) for v in learning_path.values())} 条建议")

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
                # 🔑 处理简化格式：字符串转换为列表
                stages_raw = cas.get("development_stages", [])
                if isinstance(stages_raw, str):
                    # 字符串格式 → 转换为字典列表
                    stages_list = []
                    for stage_str in stages_raw.split(";"):
                        stage_str = stage_str.strip()
                        if stage_str:
                            stages_list.append({"name": stage_str[:20], "description": stage_str})
                    stages_raw = stages_list

                drivers_raw = cas.get("core_drivers", [])
                if isinstance(drivers_raw, str):
                    # 字符串格式 → 转换为列表
                    drivers_raw = [d.strip() for d in drivers_raw.split(",") if d.strip()]

                books_raw = cas.get("related_books", [])
                if isinstance(books_raw, str):
                    # 字符串格式 → 转换为列表
                    books_raw = [b.strip() for b in books_raw.split(",") if b.strip()]

                cases.append(KeyCase(
                    name=cas.get("name", ""),
                    source_chapter=cas.get("source_chapter", ""),
                    event_description=cas.get("event_description", ""),
                    development_stages=stages_raw,
                    core_drivers=drivers_raw,
                    related_books=books_raw,
                    historical_limitations=cas.get("historical_limitations", "")
                ))

            # 构建 quotes
            quotes = []
            for q in merged_data.get("golden_quotes", []):  # 🔑 使用规范化的字段名
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