"""
Book Parser - 书籍解析统一入口

根据文件格式自动选择对应的解析器（EPUB/PDF/MOBI）。
优先使用 Docling（高性能），回退 PyMuPDF/PaddleOCR。

集成元数据增强器：Open Library + Google Books + Wikipedia
"""

import asyncio
import logging
from typing import Dict, Optional
from pathlib import Path

from parsers.base_parser import ParseResult
from parsers.epub_parser import EpubParser
from parsers.pdf_parser import PdfParser
from parsers.mobi_parser import MobiParser

# 元数据增强器
from core.metadata_enricher import enrich_book_metadata, get_metadata_enricher

# 尝试导入 Docling 解析器
try:
    from parsers.docling_parser import DoclingParser, is_docling_available
    DOCLING_AVAILABLE = is_docling_available()
except ImportError:
    DOCLING_AVAILABLE = False
    DoclingParser = None

logger = logging.getLogger("BookGraph-Agent")


class BookParser:
    """
    书籍解析统一入口

    功能：
    - 自动识别文件格式
    - 选择合适的解析器
    - 统一返回 ParseResult
    - 元数据增强（Open Library + Google Books + Wikipedia）
    """

    def __init__(self, file_path: str, config: Dict = None, llm_client=None):
        """
        初始化书籍解析器

        Args:
            file_path: 书籍文件路径
            config: 配置字典
            llm_client: LLM 客户端（用于元数据增强的 fallback）
        """
        self.file_path = Path(file_path)
        self.config = config or {}
        self.llm_client = llm_client
        self.parser: Optional[object] = None

        # 自动选择解析器
        self._select_parser()

    def _select_parser(self):
        """根据文件扩展名选择解析器（优先 Docling）"""
        suffix = self.file_path.suffix.lower()

        if suffix == '.epub':
            self.parser = EpubParser(str(self.file_path), self.config)
        elif suffix == '.pdf':
            # 🔑 优先尝试 Docling（高性能）
            if DOCLING_AVAILABLE:
                logger.info("   🚀 使用 Docling 高性能解析器")
                self.parser = DoclingParser(str(self.file_path), self.config)
            else:
                logger.info("   📄 Docling 不可用，回退 PyMuPDF")
                self.parser = PdfParser(str(self.file_path), self.config)
        elif suffix in ['.mobi', '.azw', '.azw3']:
            self.parser = MobiParser(str(self.file_path), self.config)
        else:
            raise ValueError(f"不支持的文件格式：{suffix}")

    def parse(self) -> ParseResult:
        """
        解析书籍文件

        Returns:
            ParseResult: 解析结果
        """
        if not self.parser:
            return ParseResult(
                success=False,
                error="解析器未初始化",
            )

        return self.parser.parse()

    async def parse_with_metadata_enrichment(
        self,
        title: str = None,
        author: str = None,
        isbn: str = None,
    ) -> ParseResult:
        """
        解析书籍并增强元数据

        ponytail: 集成元数据增强器，提供三层 fallback
        1. Open Library / Google Books API
        2. Wikipedia（作者信息）
        3. LLM（API 无数据时的兜底）

        Args:
            title: 书名（可选，用于元数据查询）
            author: 作者名（可选）
            isbn: ISBN 编号（可选）

        Returns:
            ParseResult: 解析结果（包含增强的元数据）
        """
        # 1. 解析书籍内容
        result = self.parse()

        if not result.success:
            return result

        # 2. 提取书名和作者（如果未提供）
        if not title:
            title = self._extract_title_from_filename()
        if not author:
            author = self._extract_author_from_filename()

        # 3. 使用元数据增强器
        logger.info(f"   📚 开始元数据增强: {title}")

        try:
            metadata = await enrich_book_metadata(
                isbn=isbn,
                title=title,
                author=author,
                llm_client=self.llm_client,
            )

            # 4. 合并元数据到 ParseResult
            if metadata:
                result.metadata = {
                    **result.metadata,
                    **metadata,
                    "title": metadata.get("title") or title,
                    "author": metadata.get("author") or author,
                    "author_intro": metadata.get("author_intro", ""),
                    "year_published": metadata.get("year_published"),
                    "publisher": metadata.get("publisher"),
                    "tags": metadata.get("tags", []),
                    "source": metadata.get("source", "api"),
                }

                logger.info(f"   ✅ 元数据增强完成: {metadata.get('source', 'unknown')}")
                if metadata.get("author_intro"):
                    logger.info(f"      作者简介: {len(metadata['author_intro'])} 字")

        except Exception as e:
            logger.warning(f"   ⚠️ 元数据增强失败: {e}")
            # 失败不影响主流程，使用原始元数据
            result.metadata["title"] = title
            result.metadata["author"] = author

        return result

    def _extract_title_from_filename(self) -> str:
        """从文件名提取书名"""
        # 移除扩展名
        stem = self.file_path.stem

        # 移除常见的后缀（作者名、年份等）
        # 例如：君主论_马基雅维利.epub → 君主论
        for sep in ["_", "-", "（", "(", "【"]:
            if sep in stem:
                stem = stem.split(sep)[0]

        return stem.strip()

    def _extract_author_from_filename(self) -> str:
        """从文件名提取作者名"""
        stem = self.file_path.stem

        # 尝试匹配常见格式：书名_作者、书名-作者
        for sep in ["_", "-"]:
            if sep in stem:
                parts = stem.split(sep)
                if len(parts) >= 2:
                    # 假设第二部分是作者
                    author_part = parts[1]
                    # 移除括号内的内容
                    for bracket in ["（", "(", "【"]:
                        if bracket in author_part:
                            author_part = author_part.split(bracket)[0]
                    return author_part.strip()

        return ""

    @staticmethod
    def detect_format(file_path: str) -> str:
        """
        检测文件格式

        Args:
            file_path: 文件路径

        Returns:
            str: 格式名称（epub/pdf/mobi）
        """
        suffix = Path(file_path).suffix.lower()

        format_map = {
            '.epub': 'epub',
            '.pdf': 'pdf',
            '.mobi': 'mobi',
            '.azw': 'mobi',
            '.azw3': 'mobi',
        }

        return format_map.get(suffix, 'unknown')

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """
        检查文件格式是否支持

        Args:
            file_path: 文件路径

        Returns:
            bool: 是否支持
        """
        supported_formats = {'.epub', '.pdf', '.mobi', '.azw', '.azw3'}
        suffix = Path(file_path).suffix.lower()
        return suffix in supported_formats
