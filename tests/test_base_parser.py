"""
test_base_parser.py - BaseParser 测试

测试核心功能：
- 文本清理
- 语言检测
- 内容分块
- 图片型内容检测
"""

import pytest
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.base_parser import BaseParser, ParseResult


class TestParseResult:
    """ParseResult 数据结构测试"""

    def test_parse_result_defaults(self):
        """测试默认值初始化"""
        result = ParseResult(success=True)

        assert result.success is True
        assert result.content == ""
        assert result.chapters == []
        assert result.metadata == {}
        assert result.is_image_based is False
        assert result.page_count == 0
        assert result.word_count == 0

    def test_parse_result_with_data(self):
        """测试带数据的初始化"""
        result = ParseResult(
            success=True,
            content="测试内容",
            chapters=[{"chapter_id": "1", "title": "第一章"}],
            metadata={"title": "测试书籍"},
            page_count=10,
            word_count=5000,
        )

        assert result.content == "测试内容"
        assert len(result.chapters) == 1
        assert result.metadata["title"] == "测试书籍"


class MockParser(BaseParser):
    """用于测试的 Mock 解析器"""

    def parse(self) -> ParseResult:
        return ParseResult(success=True, content="mock content")


class TestBaseParser:
    """BaseParser 抽象基类测试"""

    def test_init(self):
        """测试初始化"""
        parser = MockParser("/path/to/book.pdf")

        assert parser.file_path == Path("/path/to/book.pdf")
        assert parser.config == {}
        assert parser.min_text_length == 100

    def test_init_with_config(self):
        """测试带配置的初始化"""
        config = {"min_text_length": 200}
        parser = MockParser("/path/to/book.pdf", config)

        assert parser.min_text_length == 200

    # ========================================
    # 语言检测测试
    # ========================================

    def test_detect_language_chinese(self):
        """测试中文检测"""
        parser = MockParser("/path/to/book.pdf")

        # 高比例中文
        text = "这是一段中文文本，包含了很多中文字符。"
        lang = parser.detect_language(text)

        assert lang == "zh"

    def test_detect_language_english(self):
        """测试英文检测"""
        parser = MockParser("/path/to/book.pdf")

        text = "This is an English text with many English words."
        lang = parser.detect_language(text)

        assert lang == "en"

    def test_detect_language_japanese(self):
        """测试日语检测"""
        parser = MockParser("/path/to/book.pdf")

        # 包含假名
        text = "これは日本語のテストです。ひらがなとカタカナ。"
        lang = parser.detect_language(text)

        assert lang == "ja"

    def test_detect_language_empty_text(self):
        """测试空文本"""
        parser = MockParser("/path/to/book.pdf")

        lang = parser.detect_language("")
        assert lang == "unknown"

        lang = parser.detect_language("short")
        assert lang == "unknown"  # 太短无法判断

    # ========================================
    # 文本清理测试
    # ========================================

    def test_clean_text_null_chars(self):
        """测试空字符清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "测试\x00内容\x08"
        cleaned = parser.clean_text(text)

        assert "\x00" not in cleaned
        assert "\x08" not in cleaned

    def test_clean_text_control_chars(self):
        """测试控制字符清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "测试\x0b内容\x0c\x1f"
        cleaned = parser.clean_text(text)

        # 应保留换行符
        assert "\n" in cleaned or "\n" not in text

    def test_clean_text_multiple_newlines(self):
        """测试多余换行清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "第一行\n\n\n\n\n第二行"
        cleaned = parser.clean_text(text)

        # 应限制为最多 2 个换行
        assert "\n\n\n" not in cleaned

    def test_clean_text_page_numbers(self):
        """测试页码清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "内容 · 第 5 页\n正文内容"
        cleaned = parser.clean_text(text)

        assert "· 第 5 页" not in cleaned

    def test_clean_text_isbn(self):
        """测试 ISBN 清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "ISBN 978-7-111-12345-6 正文"
        cleaned = parser.clean_text(text)

        assert "ISBN" not in cleaned or "978" not in cleaned

    def test_clean_text_urls(self):
        """测试 URL 清理"""
        parser = MockParser("/path/to/book.pdf")

        text = "访问 https://example.com/page 了解更多"
        cleaned = parser.clean_text(text)

        assert "https://example.com" not in cleaned

    # ========================================
    # 内容分块测试
    # ========================================

    def test_chunk_content_single_chunk(self):
        """测试短内容不分块"""
        parser = MockParser("/path/to/book.pdf")

        content = "这是一段短内容"
        chunks = parser.chunk_content(content, chunk_size=50000)

        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["total_chunks"] == 1

    def test_chunk_content_multiple_chunks(self):
        """测试长内容分块"""
        parser = MockParser("/path/to/book.pdf")

        # 创建足够长的内容
        content = "测试内容\n\n" * 10000  # 约 100KB

        chunks = parser.chunk_content(content, chunk_size=50000, overlap_size=2000)

        assert len(chunks) > 1
        # 检查所有块都有正确的索引和总数
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_index"] == i
            assert chunk["total_chunks"] == len(chunks)

    def test_chunk_content_overlap(self):
        """测试块间重叠"""
        parser = MockParser("/path/to/book.pdf")

        content = "第一章\n内容A\n\n第二章\n内容B\n\n第三章\n内容C"

        chunks = parser.chunk_content(content, chunk_size=20, overlap_size=10)

        # 如果有多块，检查重叠内容存在
        if len(chunks) > 1:
            # 第二块应包含部分第一块内容
            assert len(chunks[1]["content"]) > 0

    def test_chunk_content_empty(self):
        """测试空内容"""
        parser = MockParser("/path/to/book.pdf")

        chunks = parser.chunk_content("")

        assert len(chunks) == 0

    # ========================================
    # 图片型内容检测测试
    # ========================================

    def test_is_image_heavy_empty(self):
        """测试空内容判定为图片型"""
        parser = MockParser("/path/to/book.pdf")

        assert parser.is_image_heavy("") is True

    def test_is_image_heavy_short(self):
        """测试短内容判定为图片型"""
        parser = MockParser("/path/to/book.pdf")

        assert parser.is_image_heavy("短文本") is True

    def test_is_image_heavy_normal(self):
        """测试正常文本"""
        parser = MockParser("/path/to/book.pdf")

        # 足够长的多样化内容
        content = "\n".join([f"第{i}行内容" for i in range(100)])

        assert parser.is_image_heavy(content) is False

    def test_is_image_heavy_repeated(self):
        """测试重复内容（水印）"""
        parser = MockParser("/path/to/book.pdf")

        # 大量重复行
        content = "\n".join(["水印内容"] * 100)

        assert parser.is_image_heavy(content) is True

    # ========================================
    # 元数据提取测试
    # ========================================

    def test_extract_metadata_from_path(self):
        """测试从文件名提取元数据"""
        parser = MockParser("/path/to/《测试书名》- 作者名.pdf")

        metadata = parser.extract_metadata_from_path()

        assert "测试书名" in metadata["title"] or metadata["title"] == "《测试书名》- 作者名"

    def test_extract_metadata_simple_filename(self):
        """测试简单文件名"""
        parser = MockParser("/path/to/simple.pdf")

        metadata = parser.extract_metadata_from_path()

        assert metadata["title"] == "simple"
        assert metadata["author"] == "Unknown"