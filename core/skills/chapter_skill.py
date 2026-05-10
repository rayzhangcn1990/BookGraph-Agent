"""
章节结构解析 Skill

从书籍内容中提取章节结构信息：
- 章节编号
- 章节标题
- 核心论点
- 底层逻辑
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class ChapterSkill(BaseSkill):
    """章节结构解析 Skill"""

    name = "chapter"
    section_name = "章节结构"
    output_field = "chapter_summaries"
    min_items = 1

    @property
    def prompt_template(self) -> str:
        return """请分析以下书籍内容，提取章节结构信息。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "chapter_summaries": [    {{      "chapter_number": "1",      "title": "章节标题（必须是实际的章节名）",      "core_argument": "本章核心论点（一句话概括，必须有实质内容，严禁模板化）",      "underlying_logic": "前提假设：[内容]→推理链条：[内容]→核心结论：[内容]",      "related_books": ["关联书籍名称"],      "critical_questions": ["批判性问题1", "批判性问题2"]    }}  ]
}}

【核心约束 - 最高优先级】
1. **严禁模板化内容**：
   - 禁止"本章探讨了..."、"本章分析了..."、"作者通过逻辑推理展开论述"等模板句式
   - 核心论点必须具体、有信息量，反映章节实际内容

2. **底层逻辑格式**：
   - 必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
   - 每部分必须有实质内容，不能是占位符

3. **标题有效性**：
   - 章节标题必须是实际章节名，不能是正文片段
   - 标题长度不超过100字符
   - 不能以"第一，"、"第二天早上"等正文特征开头

4. **数量要求**：
   - 提取所有可识别的章节，不少于1个
   - 如果确实无法提取章节，返回空数组 []

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["chapter_summaries"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验章节结果"""
        errors = []

        # Layer 1: 结构校验
        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        # Layer 2: 字段校验
        if "chapter_summaries" not in result:
            errors.append("缺失字段: chapter_summaries")

        chapters = result.get("chapter_summaries", [])

        # Layer 3: 数量校验（允许空数组，但需要说明）
        if len(chapters) == 0:
            # 检查是否有说明
            if result.get("extraction_status") == "failed":
                # 失败状态，跳过后续校验
                return False, errors
            errors.append("未提取到任何章节")

        # Layer 4: 内容质量校验
        for i, chapter in enumerate(chapters):
            # 标题校验
            title = chapter.get("title", "")
            if not self._is_valid_chapter_title(title):
                errors.append(f"章节{i+1} 标题无效: {title[:30]}")

            # 核心论点校验
            core_arg = chapter.get("core_argument", "")
            if self._is_template_content(core_arg):
                errors.append(f"章节{i+1} 核心论点为模板化内容")

            # 底层逻辑校验
            logic = chapter.get("underlying_logic", "")
            if not self._is_valid_logic_format(logic):
                errors.append(f"章节{i+1} 底层逻辑格式错误")

        return len(errors) == 0, errors

    def generate_markdown(
        self,
        result: Dict,
        extractions: List = None  # 🆕 兼容参数
    ) -> str:
        """生成章节 Markdown"""
        lines = []

        chapters = result.get("chapter_summaries", [])

        if not chapters:
            # 失败或空结果
            status = result.get("extraction_status", "")
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 章节结构解析异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            lines.append("> 此部分内容需要手动修复")
            return "\n".join(lines)

        for chapter in chapters:
            chapter_number = chapter.get("chapter_number", "?")
            title = chapter.get("title", "未命名章节")
            core_arg = self._clean_content(chapter.get("core_argument", ""))
            logic = self._clean_content(chapter.get("underlying_logic", ""))
            related_books = chapter.get("related_books", [])
            critical_questions = chapter.get("critical_questions", [])

            # 🔑 强化格式：详细表格展示
            lines.append(f"### 第{chapter_number}章：{title}")
            lines.append("")
            lines.append("| 要素 | 内容 |")
            lines.append("|------|------|")

            # 核心论点
            if core_arg:
                lines.append(f"| 🎯 核心论点 | {core_arg} |")

            # 底层逻辑（拆解单行格式）
            if logic:
                import re
                m = re.match(r'前提假设：(.+?)\s*→\s*推理链条：(.+?)\s*→\s*核心结论：(.+)$', logic)
                if m:
                    lines.append(f"| 📊 前提假设 | {m.group(1).strip()} |")
                    lines.append(f"| 🔗 推理链条 | {m.group(2).strip()} |")
                    lines.append(f"| ✅ 核心结论 | {m.group(3).strip()} |")
                else:
                    lines.append(f"| 🧠 底层逻辑 | {logic} |")

            # 关联书籍
            if related_books:
                related_str = ", ".join([f"[[{b}]]" for b in related_books])
                lines.append(f"| 📚 关联书籍 | {related_str} |")

            # 批判性问题
            if critical_questions:
                questions_str = "; ".join(critical_questions[:3])
                lines.append(f"| ⚠️ 批判性问题 | {questions_str} |")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # 私有方法
    # ═══════════════════════════════════════════════════════════

    def _combine_chunks(
        self,
        chunks: List[Dict],
        max_chunks: int = 999,
        max_chars_per_chunk: int = 3000
    ) -> Tuple[str, Dict]:
        """
        合并 chunks 内容（章节专用版）

        🆕 改造：
        1. 返回 Tuple[str, Dict]（与 base_skill 一致）
        2. 生成位置映射

        Args:
            chunks: chunk 列表（Dict 格式，包含 char_interval）
            max_chunks: 不限制（遍历全部）
            max_chars_per_chunk: 每块只取 3000 字符

        Returns:
            Tuple[str, Dict]: (合并内容, 位置映射)
        """
        combined = []
        chunk_positions = []
        source_text = ""
        total_chunks = len(chunks)

        for chunk in chunks:
            content = chunk.get('content', '')
            label = chunk.get('label', f'Chunk {chunk.get("chunk_index", 0)}')
            char_interval = chunk.get('char_interval', {'start_pos': 0, 'end_pos': 0})

            # 🆕 记录位置信息
            chunk_positions.append({
                'chunk_index': chunk.get('chunk_index', 0),
                'start_pos': char_interval.get('start_pos', 0),
                'end_pos': char_interval.get('end_pos', 0),
                'label': label,
                'combined_start': len("\n\n---\n\n".join(combined)) if combined else 0
            })

            # 保存完整原文
            if not source_text and chunk.get('source_text'):
                source_text = chunk.get('source_text', '')

            truncated_content = content[:max_chars_per_chunk]
            combined.append(f"【{label}】\n{truncated_content}")

        result_content = "\n\n---\n\n".join(combined)
        total_chars = len(result_content)

        position_map = {
            'source_text': source_text,
            'chunk_positions': chunk_positions,
            'combined_length': total_chars
        }

        logger.info(f"[chapter] 全量采样: {total_chunks}/{total_chunks} chunks (100%覆盖), {total_chars} 字符")

        return result_content, position_map

    def _is_valid_chapter_title(self, title: str) -> bool:
        """校验章节标题有效性"""
        if not title:
            return False

        # 过长标题可能是正文片段
        if len(title) > 100:
            return False

        # 正文片段特征
        invalid_patterns = [
            "第一，", "第二天早上", "按照安排",
            "▲", "★", "●", "◆", "◇", "◆◆",
            "...", "……", "等等", "例如", "比如",
        ]

        for pattern in invalid_patterns:
            if title.startswith(pattern) or pattern in title[:20]:
                return False

        return True

    def _is_template_content(self, content: str) -> bool:
        """检测模板化内容"""
        template_patterns = [
            "本章探讨了", "本章分析了", "本章讨论了",
            "本章阐述了", "通过逻辑推理展开论述",
            "进行系统性阐述", "提供了新的分析框架",
            "作者通过", "阐述了", "探讨了",
        ]

        for pattern in template_patterns:
            if pattern in content:
                return True

        return False

    def _is_valid_logic_format(self, logic: str) -> bool:
        """校验底层逻辑格式"""
        if not logic:
            return False

        # 检查是否包含必要的三部分
        has_premise = "前提假设" in logic or "前提" in logic
        has_chain = "推理链条" in logic or "推理" in logic
        has_conclusion = "核心结论" in logic or "结论" in logic

        return has_premise and has_chain and has_conclusion

    def _clean_content(self, content: str) -> str:
        """清理内容"""
        if not content:
            return ""

        # 移除占位符
        placeholders = ["待分析", "待补充", "TBD", "TODO", "N/A"]
        for ph in placeholders:
            if content.strip() == ph:
                return ""

        return content.strip()