"""
Docling Parser - 高性能文档解析器

使用 IBM Docling 引擎解析 PDF/DOCX/PPTX，输出结构化 Markdown。
相比 PaddleOCR 提速 5-10x，且保留完整的文档结构（标题层级、表格、公式）。

依赖：
    pip install docling

参考：
    https://github.com/DS4SD/docling
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_parser import BaseParser, ParseResult

logger = logging.getLogger("BookGraph-Agent")

# 尝试导入 Docling
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import PdfFormatOption
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.info("Docling 未安装，将使用 PyMuPDF 回退。安装: pip install docling")


class DoclingParser(BaseParser):
    """
    Docling 文档解析器

    功能：
    - 高性能 PDF 解析（比 PaddleOCR 快 5-10x）
    - 自动识别标题层级（## ### ####）
    - 保留表格、公式、代码块结构
    - 支持多栏布局、页眉页脚过滤
    - 输出干净的 Markdown 格式

    支持：
    - PDF（文字版和扫描版）
    - DOCX
    - PPTX
    - HTML
    """

    def __init__(self, file_path: str, config: Dict = None):
        super().__init__(file_path, config)
        self.config = config or {}

        # Docling 配置
        self.use_ocr = self.config.get('use_ocr', True)  # 对扫描版启用 OCR
        self.ocr_lang = self.config.get('ocr_lang', ['zh', 'en'])
        self.preserve_tables = self.config.get('preserve_tables', True)
        self.preserve_code = self.config.get('preserve_code', True)

    def parse(self) -> ParseResult:
        """
        解析文档文件

        Returns:
            ParseResult: 包含结构化 Markdown 和章节信息
        """
        if not DOCLING_AVAILABLE:
            return ParseResult(
                success=False,
                error="Docling 未安装：pip install docling",
            )

        try:
            logger.info(f"📄 使用 Docling 解析: {self.file_path.name}")

            # 创建转换器
            converter = self._create_converter()

            # 转换文档
            result = converter.convert(str(self.file_path))

            # 导出为 Markdown
            markdown = result.document.export_to_markdown()

            # 提取元数据
            metadata = self._extract_metadata(result)

            # 从 Markdown 提取章节
            chapters = self._extract_chapters_from_markdown(markdown)

            # 统计
            word_count = len(markdown)
            page_count = len(result.document.pages) if hasattr(result.document, 'pages') else 0

            logger.info(f"   ✅ 解析完成: {word_count} 字符, {len(chapters)} 章节")

            return ParseResult(
                success=True,
                content=markdown,
                chapters=chapters,
                metadata=metadata,
                is_image_based=False,  # Docling 统一输出文本
                page_count=page_count,
                word_count=word_count,
            )

        except Exception as e:
            logger.error(f"❌ Docling 解析失败: {str(e)[:100]}")
            return ParseResult(
                success=False,
                error=f"Docling 解析失败：{str(e)}",
                metadata={"file_path": str(self.file_path)},
            )

    def _create_converter(self) -> 'DocumentConverter':
        """
        创建 Docling 转换器

        Returns:
            DocumentConverter: 配置好的转换器
        """
        # 基础转换器
        converter = DocumentConverter()

        # TODO: 添加高级配置（OCR 语言、表格识别等）
        # 需要深入研究 Docling API

        return converter

    def _extract_metadata(self, result) -> Dict:
        """
        从 Docling 结果提取元数据

        Args:
            result: Docling 转换结果

        Returns:
            Dict: 元数据字典
        """
        metadata = {
            "title": self.file_path.stem,
            "author": "Unknown",
            "file_name": self.file_path.name,
            "file_path": str(self.file_path),
            "parser": "docling",
        }

        # 尝试从文档属性提取
        if hasattr(result.document, 'metadata'):
            doc_meta = result.document.metadata

            if hasattr(doc_meta, 'title') and doc_meta.title:
                metadata["title"] = doc_meta.title
            if hasattr(doc_meta, 'author') and doc_meta.author:
                metadata["author"] = doc_meta.author

        return metadata

    def _extract_chapters_from_markdown(self, markdown: str) -> List[Dict]:
        """
        从 Markdown 提取章节结构

        Docling 输出的 Markdown 已经包含标准标题层级（# ## ###）。
        此方法解析标题，将内容按章节组织。

        Args:
            markdown: Markdown 内容

        Returns:
            List[Dict]: 章节列表
        """
        chapters = []
        lines = markdown.split('\n')

        current_chapter = None
        current_content = []
        chapter_id = 0

        # 匹配 ## 标题（一级章节）和 ### 标题（二级章节）
        chapter_pattern = re.compile(r'^(#{1,3})\s+(.+)$')

        for line in lines:
            match = chapter_pattern.match(line)

            if match:
                # 保存上一章
                if current_chapter:
                    chapters.append({
                        "chapter_id": current_chapter["id"],
                        "title": current_chapter["title"],
                        "content": "\n".join(current_content),
                        "level": current_chapter["level"],
                    })

                # 开始新章节
                level = len(match.group(1))
                title = match.group(2).strip()

                # 只将 ## 作为主章节（忽略 ### 子标题）
                if level == 2:
                    chapter_id += 1
                    current_chapter = {
                        "id": str(chapter_id),
                        "title": title,
                        "level": level,
                    }
                    current_content = []
                elif current_chapter:
                    # 子标题添加到当前章节内容
                    current_content.append(line)
            elif current_chapter:
                current_content.append(line)

        # 保存最后一章
        if current_chapter:
            chapters.append({
                "chapter_id": current_chapter["id"],
                "title": current_chapter["title"],
                "content": "\n".join(current_content),
                "level": current_chapter["level"],
            })

        # 如果没有检测到章节，将整个文档作为一章
        if not chapters:
            chapters.append({
                "chapter_id": "1",
                "title": "完整内容",
                "content": markdown,
                "level": 1,
            })

        return chapters


def is_docling_available() -> bool:
    """检查 Docling 是否可用"""
    return DOCLING_AVAILABLE
