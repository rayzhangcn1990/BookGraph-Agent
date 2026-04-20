"""
Book Parser - 书籍解析统一入口

根据文件格式自动选择对应的解析器（EPUB/PDF/MOBI）。
"""

from typing import Dict, Optional
from pathlib import Path

from parsers.base_parser import ParseResult
from parsers.epub_parser import EpubParser
from parsers.pdf_parser import PdfParser
from parsers.mobi_parser import MobiParser


class BookParser:
    """
    书籍解析统一入口
    
    功能：
    - 自动识别文件格式
    - 选择合适的解析器
    - 统一返回 ParseResult
    """

    def __init__(self, file_path: str, config: Dict = None):
        """
        初始化书籍解析器
        
        Args:
            file_path: 书籍文件路径
            config: 配置字典
        """
        self.file_path = Path(file_path)
        self.config = config or {}
        self.parser: Optional[object] = None
        
        # 自动选择解析器
        self._select_parser()

    def _select_parser(self):
        """根据文件扩展名选择解析器"""
        suffix = self.file_path.suffix.lower()
        
        if suffix == '.epub':
            self.parser = EpubParser(str(self.file_path), self.config)
        elif suffix == '.pdf':
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
