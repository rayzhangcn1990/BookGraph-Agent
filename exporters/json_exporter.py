"""
JSON 导出器

将 BookGraph 转换为结构化 JSON 格式。
支持知识库持久化和跨书籍查询。

使用方法：
```python
from exporters.json_exporter import JSONExporter

exporter = JSONExporter()
json_data = exporter.export(book_graph)
exporter.export_to_file(book_graph, output_path)
```
"""

import json
import logging
from typing import Dict, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("BookGraph-Agent")


class JSONExporter:
    """
    JSON 导出器

    输出格式：结构化 JSON

    特性：
    - 完整保留 BookGraph 结构
    - 添加导出元数据（时间戳、版本）
    - 支持 Unicode（ensure_ascii=False）
    - 美化输出（indent=2）
    """

    def __init__(self):
        """初始化导出器"""
        self.version = "1.0.0"

    def export(self, book_graph: Dict) -> Dict[str, Any]:
        """
        导出为 JSON 格式

        Args:
            book_graph: BookGraph 数据

        Returns:
            Dict: 结构化 JSON 数据
        """
        # 添加导出元数据
        export_data = {
            "version": self.version,
            "exported_at": datetime.now().isoformat(),
            "exported_by": "BookGraph-Agent",
            "data": book_graph
        }

        return export_data

    def export_to_file(self, book_graph: Dict, output_path: Path):
        """
        导出到文件

        Args:
            book_graph: BookGraph 数据
            output_path: 输出文件路径
        """
        export_data = self.export(book_graph)

        # 写入文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        logger.info(f"JSON 已导出: {output_path}")

    def export_for_knowledge_base(self, book_graph: Dict) -> Dict[str, Any]:
        """
        导出为知识库格式（简化版，仅保留关键字段）

        Args:
            book_graph: BookGraph 数据

        Returns:
            Dict: 知识库格式数据
        """
        # 提取关键字段
        metadata = book_graph.get("metadata", {})
        chapters = book_graph.get("chapters", [])
        concepts = book_graph.get("core_concepts", [])
        insights = book_graph.get("key_insights", [])
        quotes = book_graph.get("key_quotes", [])

        # 简化结构
        simplified = {
            "title": metadata.get("title", "未知书籍"),
            "author": metadata.get("author", "未知作者"),
            "discipline": metadata.get("discipline", "未分类"),
            "chapters": [
                {
                    "title": ch.get("title", ""),
                    "core_argument": ch.get("core_argument", "")
                }
                for ch in chapters
            ],
            "concepts": [
                {
                    "name": c.get("name", ""),
                    "definition": c.get("definition", "")
                }
                for c in concepts
            ],
            "insights": [i.get("insight", "") for i in insights],
            "quotes": [q.get("quote", "") for q in quotes]
        }

        return simplified


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def export_json(book_graph: Dict) -> Dict[str, Any]:
    """
    导出 JSON 的便捷函数

    Args:
        book_graph: BookGraph 数据

    Returns:
        Dict: JSON 数据
    """
    exporter = JSONExporter()
    return exporter.export(book_graph)


def save_json(book_graph: Dict, output_path: Path):
    """
    保存 JSON 的便捷函数

    Args:
        book_graph: BookGraph 数据
        output_path: 输出文件路径
    """
    exporter = JSONExporter()
    exporter.export_to_file(book_graph, output_path)
