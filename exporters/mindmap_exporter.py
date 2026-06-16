"""
思维导图导出器

基于 ebook-to-mindmap 项目模式实现。
将 BookGraph 转换为 Mermaid 思维导图格式。

核心功能：
1. 章节分组标签（按章节自动分组）
2. 核心概念节点（展开到二级）
3. 关键洞见节点（展开到一级）
4. Markdown 输出（支持 Obsidian 预览）

使用方法：
```python
from exporters.mindmap_exporter import MindmapExporter

exporter = MindmapExporter()
mermaid_code = exporter.export(book_graph)
```
"""

import logging
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("BookGraph-Agent")


class MindmapExporter:
    """
    思维导图导出器

    输出格式：Mermaid mindmap

    特性：
    - 章节分组（按章节结构组织）
    - 概念展开（核心概念展开到二级）
    - 洞见标注（关键洞见高亮显示）
    - Markdown 兼容（支持 Obsidian 预览）
    """

    def __init__(self):
        """初始化导出器"""
        self.max_chapters = 20  # 最多显示20个章节
        self.max_concepts = 15  # 最多显示15个概念
        self.max_insights = 10  # 最多显示10个洞见

    def export(self, book_graph: Dict) -> str:
        """
        导出为 Mermaid 思维导图

        Args:
            book_graph: BookGraph 数据

        Returns:
            str: Mermaid mindmap 代码
        """
        # 提取书名
        book_title = book_graph.get("metadata", {}).get("title", "未知书籍")

        # 构建 mindmap 结构
        lines = ["mindmap"]
        lines.append(f"  root(({book_title}))")

        # 1. 章节结构
        chapters = book_graph.get("chapters", [])
        if chapters:
            lines.append("    章节")
            for i, chapter in enumerate(chapters[:self.max_chapters]):
                chapter_title = chapter.get("title", f"第{i+1}章")
                # 移除过长的标题
                if len(chapter_title) > 30:
                    chapter_title = chapter_title[:30] + "..."
                lines.append(f"      {chapter_title}")

        # 2. 核心概念
        concepts = book_graph.get("core_concepts", [])
        if concepts:
            lines.append("    核心概念")
            for concept in concepts[:self.max_concepts]:
                concept_name = concept.get("name", "未知概念")
                # 移除特殊字符
                concept_name = self._sanitize_text(concept_name)
                lines.append(f"      {concept_name}")

                # 展开定义（如果有）
                definition = concept.get("definition", "")
                if definition and len(definition) < 50:
                    definition = self._sanitize_text(definition)
                    lines.append(f"        {definition}")

        # 3. 关键洞见
        insights = book_graph.get("key_insights", [])
        if insights:
            lines.append("    关键洞见")
            for insight in insights[:self.max_insights]:
                insight_text = insight.get("insight", "未知洞见")
                # 截断过长的洞见
                if len(insight_text) > 40:
                    insight_text = insight_text[:40] + "..."
                insight_text = self._sanitize_text(insight_text)
                lines.append(f"      {insight_text}")

        # 4. 关键案例
        cases = book_graph.get("key_cases", [])
        if cases:
            lines.append("    关键案例")
            for case in cases[:5]:
                case_name = case.get("case_name", "未知案例")
                case_name = self._sanitize_text(case_name)
                lines.append(f"      {case_name}")

        return "\n".join(lines)

    def export_to_file(self, book_graph: Dict, output_path: Path):
        """
        导出到文件

        Args:
            book_graph: BookGraph 数据
            output_path: 输出文件路径
        """
        mermaid_code = self.export(book_graph)

        # 生成 Markdown 内容
        markdown_content = f"""# {book_graph.get('metadata', {}).get('title', '未知书籍')} - 思维导图

```mermaid
{mermaid_code}
```

---

**说明:**
- 本思维导图由 BookGraph-Agent 自动生成
- 章节结构按原书顺序排列
- 核心概念展开到定义层级
- 关键洞见直接展示核心观点
"""

        # 写入文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        logger.info(f"思维导图已导出: {output_path}")

    def _sanitize_text(self, text: str) -> str:
        """
        清理文本（移除特殊字符）

        Args:
            text: 原始文本

        Returns:
            str: 清理后的文本
        """
        # Mermaid 特殊字符转义
        replacements = {
            '"': "'",
            "(": "（",
            ")": "）",
            "[": "【",
            "]": "】",
            "{": "｛",
            "}": "｝",
            ":": "：",
            ";": "；",
            "\n": " ",
            "\r": "",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        return text.strip()


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def export_mindmap(book_graph: Dict) -> str:
    """
    导出思维导图的便捷函数

    Args:
        book_graph: BookGraph 数据

    Returns:
        str: Mermaid mindmap 代码
    """
    exporter = MindmapExporter()
    return exporter.export(book_graph)


def save_mindmap(book_graph: Dict, output_path: Path):
    """
    保存思维导图的便捷函数

    Args:
        book_graph: BookGraph 数据
        output_path: 输出文件路径
    """
    exporter = MindmapExporter()
    exporter.export_to_file(book_graph, output_path)
