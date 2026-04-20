"""
test_obsidian_writer.py - ObsidianWriter 测试

测试核心功能：
- 文件名安全处理
- 目录结构管理
- 文件写入
- 备份机制
"""

import pytest
from pathlib import Path
import sys
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.obsidian_writer import ObsidianWriter
from schemas.book_graph_schema import (
    BookGraph, BookMetadata, DisciplineType,
    TimeBackground, CriticalAnalysis
)


class TestObsidianWriterInit:
    """ObsidianWriter 初始化测试"""

    def test_init_default(self):
        """测试默认初始化"""
        writer = ObsidianWriter()

        assert writer.vault_path == Path("")
        assert writer.graph_root == '📚 知识图谱'

    def test_init_with_config(self):
        """测试带配置初始化"""
        config = {
            'vault_path': '/tmp/test_vault',
            'graph_root': '测试图谱',
        }
        writer = ObsidianWriter(config)

        assert writer.vault_path == Path('/tmp/test_vault')
        assert writer.graph_root == '测试图谱'

    def test_init_with_discipline_paths(self):
        """测试学科路径配置"""
        config = {
            'vault_path': '/tmp/test_vault',
            'discipline_paths': {
                '哲学': '哲学目录',
                '经济学': '经济学目录',
            },
        }
        writer = ObsidianWriter(config)

        assert '哲学' in writer.discipline_paths


class TestFilenameSanitization:
    """文件名安全处理测试"""

    def test_sanitize_illegal_chars(self):
        """测试非法字符处理"""
        writer = ObsidianWriter()

        # 包含非法字符的文件名
        filename = writer._sanitize_filename("书名<>:\"/\\|?*测试")

        # 非法字符应被替换
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            assert char not in filename

    def test_sanitize_strip_spaces(self):
        """测试前后空格"""
        writer = ObsidianWriter()

        filename = writer._sanitize_filename("  书名  ")

        assert filename == "书名"

    def test_sanitize_length_limit(self):
        """测试长度限制"""
        writer = ObsidianWriter()

        # 超长文件名
        long_name = "a" * 300
        filename = writer._sanitize_filename(long_name)

        assert len(filename) <= 200

    def test_sanitize_normal_name(self):
        """测试正常文件名"""
        writer = ObsidianWriter()

        filename = writer._sanitize_filename("正常书名")

        assert filename == "正常书名"


class TestDisciplinePath:
    """学科路径测试"""

    def test_get_discipline_path_configured(self):
        """测试已配置的学科路径"""
        config = {
            'discipline_paths': {'哲学': '📚 知识图谱/哲学'},
        }
        writer = ObsidianWriter(config)

        path = writer._get_discipline_path('哲学')

        assert str(path) == '📚 知识图谱/哲学'

    def test_get_discipline_path_default(self):
        """测试默认学科路径"""
        writer = ObsidianWriter({'graph_root': '📚 知识图谱'})

        path = writer._get_discipline_path('经济学')

        assert '经济学' in str(path)


class TestVaultStats:
    """Vault 统计测试"""

    def test_get_vault_stats_empty(self):
        """测试空 Vault"""
        writer = ObsidianWriter({'vault_path': '/nonexistent/path'})

        stats = writer.get_vault_stats()

        assert stats['total_books'] == 0
        assert stats['total_disciplines'] == 0


class TestObsidianWriterWithTempVault:
    """使用临时 Vault 的测试"""

    @pytest.fixture
    def temp_vault(self):
        """创建临时 Vault"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_ensure_discipline_structure(self, temp_vault):
        """测试目录结构创建"""
        writer = ObsidianWriter({
            'vault_path': str(temp_vault),
            'graph_root': '知识图谱',
            'subdirectories': {
                'books': '书籍',
                'discipline': '学科',
            },
        })

        writer.ensure_discipline_structure('测试学科')

        # 检查目录是否创建
        discipline_dir = temp_vault / '知识图谱' / '测试学科'
        assert discipline_dir.exists()

        # 检查子目录
        books_dir = discipline_dir / '书籍'
        assert books_dir.exists()

    def test_write_discipline_graph(self, temp_vault):
        """测试写入学科图谱"""
        writer = ObsidianWriter({
            'vault_path': str(temp_vault),
            'graph_root': '知识图谱',
            'subdirectories': {'discipline': '学科'},
        })

        content = "# 测试学科图谱\n\n这是测试内容。"
        path = writer.write_discipline_graph('测试学科', content)

        # 检查文件是否创建
        assert path.exists()
        assert '测试学科学科图谱.md' in str(path)

        # 检查内容
        with open(path, 'r', encoding='utf-8') as f:
            written_content = f.read()
        assert written_content == content

    def test_write_book_graph(self, temp_vault):
        """测试写入书籍图谱"""
        writer = ObsidianWriter({
            'vault_path': str(temp_vault),
            'graph_root': '知识图谱',
            'discipline_paths': {'哲学': '知识图谱/哲学'},
            'subdirectories': {'books': '书籍'},
        })

        # 创建最小 BookGraph
        from schemas.book_graph_schema import TimeBackground, CriticalAnalysis

        book_graph = BookGraph(
            metadata=BookMetadata(
                title="测试书籍",
                author="测试作者",
                author_intro="简介",
                discipline=DisciplineType.哲学,
            ),
            time_background=TimeBackground(
                macro_background="",
                micro_background="",
                core_contradiction="",
            ),
            critical_analysis=CriticalAnalysis(
                feminist_perspective="",
                postcolonial_perspective="",
            ),
        )

        from schemas.book_graph_schema import TimeBackground, CriticalAnalysis

        content = "# 测试书籍\n\n内容"
        path = writer.write_book_graph(book_graph, content)

        # 检查文件
        assert path.exists()
        assert '测试书籍.md' in str(path)

    def test_backup_existing_file(self, temp_vault):
        """测试备份现有文件"""
        writer = ObsidianWriter({
            'vault_path': str(temp_vault),
            'graph_root': '知识图谱',
            'discipline_paths': {'哲学': '知识图谱/哲学'},
            'subdirectories': {'discipline': '学科'},
        })

        # 先写入一次
        writer.ensure_discipline_structure('哲学')
        writer.write_discipline_graph('哲学', "原内容")

        # 再次写入（触发备份）
        writer.write_discipline_graph('哲学', "新内容")

        # 检查备份文件存在
        discipline_dir = temp_vault / '知识图谱' / '哲学' / '学科'
        backups = list(discipline_dir.glob("*backup*.md"))

        assert len(backups) >= 1

    def test_get_all_books_in_discipline(self, temp_vault):
        """测试获取学科书籍列表"""
        writer = ObsidianWriter({
            'vault_path': str(temp_vault),
            'graph_root': '知识图谱',
            'discipline_paths': {'哲学': '知识图谱/哲学'},
            'subdirectories': {'books': '书籍'},
        })

        # 创建一些书籍文件
        writer.ensure_discipline_structure('哲学')
        books_dir = temp_vault / '知识图谱' / '哲学' / '书籍'

        (books_dir / '书籍A.md').write_text('内容A')
        (books_dir / '书籍B.md').write_text('内容B')
        (books_dir / '.hidden.md').write_text('隐藏')

        books = writer.get_all_books_in_discipline('哲学')

        # 应包含 A 和 B，不包含隐藏文件
        assert '书籍A' in books
        assert '书籍B' in books
        assert '.hidden' not in books


class TestReadOperations:
    """读取操作测试"""

    def test_read_existing_discipline_graph_not_found(self):
        """测试读取不存在的内容"""
        writer = ObsidianWriter({'vault_path': '/nonexistent'})

        content = writer.read_existing_discipline_graph('哲学')

        assert content is None

    def test_read_book_graph_not_found(self):
        """测试读取不存在的书籍"""
        writer = ObsidianWriter({'vault_path': '/nonexistent'})

        content = writer.read_book_graph('哲学', '不存在书籍')

        assert content is None