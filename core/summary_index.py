"""
摘要层索引：生成章节摘要和全书摘要，用于宏观问题快速检索。
"""

import logging
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger("BookGraph-Agent")


def generate_chapter_summary(book_graph, output_dir: Path) -> None:
    """
    生成章节摘要文件 `_chapter_summary.md`，汇总所有章节核心论点。

    Args:
        book_graph: BookGraph 对象
        output_dir: 输出目录（通常为 Obsidian 书籍目录）
    """
    chapters = getattr(book_graph, 'chapters', [])
    if not chapters:
        logger.warning("没有章节信息，跳过章节摘要生成")
        return

    lines = []
    lines.append("---")
    lines.append("title: 章节摘要")
    lines.append("type: summary-index")
    lines.append("---")
    lines.append("")
    lines.append("# 章节摘要")
    lines.append("")
    lines.append("本书各章节的核心论点汇总，便于快速定位关键内容。")
    lines.append("")

    for ch in chapters:
        title = getattr(ch, 'title', '未命名章节')
        ch_num = getattr(ch, 'chapter_number', '?')
        core_arg = getattr(ch, 'core_argument', '')
        logic = getattr(ch, 'underlying_logic', '')
        lines.append(f"## 第{ch_num}章：{title}")
        lines.append("")
        if core_arg:
            lines.append(f"> **核心论点**：{core_arg}")
        if logic:
            lines.append(f"> **底层逻辑**：{logic}")
        lines.append("")
        lines.append("---")
        lines.append("")

    summary_path = output_dir / "_chapter_summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.info(f"📄 生成章节摘要: {summary_path}")


def generate_book_summary(book_graph, output_dir: Path) -> None:
    """
    生成全书摘要文件 `_book_summary.md`，包含全书核心问题、主要结论、学习路径。

    Args:
        book_graph: BookGraph 对象
        output_dir: 输出目录
    """
    metadata = getattr(book_graph, 'metadata', None)
    time_bg = getattr(book_graph, 'time_background', None)
    critical = getattr(book_graph, 'critical_analysis', None)
    learning = getattr(book_graph, 'learning_path', {})

    title = getattr(metadata, 'title', '未知') if metadata else '未知'
    author = getattr(metadata, 'author', '未知') if metadata else '未知'
    macro = getattr(time_bg, 'macro_background', '') if time_bg else ''
    core_contradiction = getattr(time_bg, 'core_contradiction', '') if time_bg else ''

    lines = []
    lines.append("---")
    lines.append(f"title: {title} - 全书摘要")
    lines.append("type: summary-index")
    lines.append("---")
    lines.append("")
    lines.append(f"# 《{title}》全书摘要")
    lines.append("")
    lines.append(f"**作者**：{author}")
    lines.append("")
    if macro:
        lines.append("## 宏观背景")
        lines.append("")
        lines.append(macro)
        lines.append("")
    if core_contradiction:
        lines.append("## 核心矛盾")
        lines.append("")
        lines.append(core_contradiction)
        lines.append("")
    lines.append("## 主要结论")
    lines.append("")
    # 从关键洞见中提取
    insights = getattr(book_graph, 'key_insights', [])
    if insights:
        for ins in insights[:5]:
            lines.append(f"- **{ins.title}**：{ins.description[:200]}...")
    else:
        lines.append("（待补充）")
    lines.append("")
    lines.append("## 学习路径")
    lines.append("")
    for level in ['beginner', 'intermediate', 'advanced', 'practice']:
        if level in learning:
            items = learning[level]
            if items:
                lines.append(f"### {level.capitalize()}")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")
    summary_path = output_dir / "_book_summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.info(f"📖 生成全书摘要: {summary_path}")
