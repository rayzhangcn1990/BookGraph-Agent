"""
Path Manager - 路径管理工具模块

提供统一的路径管理和文件名处理功能。
"""

from typing import Optional
from pathlib import Path
import re
import unicodedata


class PathManager:
    """
    路径管理器
    
    功能：
    - 生成标准化的文件路径
    - 处理文件名中的特殊字符
    - 管理 Obsidian Vault 路径结构
    """

    def __init__(self, vault_path: str, graph_root: str = "📚 知识图谱"):
        """
        初始化路径管理器
        
        Args:
            vault_path: Obsidian Vault 根路径
            graph_root: 图谱根目录名称
        """
        self.vault_path = Path(vault_path)
        self.graph_root = graph_root

    def get_book_graph_path(
        self, 
        discipline: str, 
        book_title: str
    ) -> Path:
        """
        获取书籍图谱文件路径
        
        Args:
            discipline: 学科名称
            book_title: 书名
            
        Returns:
            Path: 完整的文件路径
        """
        discipline_dir = self.vault_path / self.graph_root / discipline
        books_dir = discipline_dir / "书籍图谱"
        
        safe_title = self.sanitize_filename(book_title)
        return books_dir / f"{safe_title}.md"

    def get_discipline_graph_path(self, discipline: str) -> Path:
        """
        获取学科图谱文件路径
        
        Args:
            discipline: 学科名称
            
        Returns:
            Path: 完整的文件路径
        """
        discipline_dir = self.vault_path / self.graph_root / discipline
        return discipline_dir / "学科图谱" / f"{discipline}学科图谱.md"

    def get_concept_library_path(self, discipline: str) -> Path:
        """
        获取概念词汇库文件路径
        
        Args:
            discipline: 学科名称
            
        Returns:
            Path: 完整的文件路径
        """
        discipline_dir = self.vault_path / self.graph_root / discipline
        return discipline_dir / "概念词汇库" / f"{discipline}概念库.md"

    def get_beginner_guide_path(self, discipline: str) -> Path:
        """
        获取初学者指南文件路径
        
        Args:
            discipline: 学科名称
            
        Returns:
            Path: 完整的文件路径
        """
        discipline_dir = self.vault_path / self.graph_root / discipline
        return discipline_dir / "入门指南" / f"{discipline}入门指南.md"

    def sanitize_filename(self, name: str) -> str:
        """
        生成安全的文件名
        
        处理特殊字符，确保文件名在 macOS/Linux/Windows 上都合法。
        
        Args:
            name: 原始名称
            
        Returns:
            str: 安全的文件名
        """
        # 移除或替换非法字符
        illegal_chars = {
            '<': '_', '>': '_', ':': '_', '"': '_',
            '/': '_', '\\': '_', '|': '_', '?': '_', '*': '_',
        }
        
        for char, replacement in illegal_chars.items():
            name = name.replace(char, replacement)
        
        # 移除控制字符
        name = ''.join(c for c in name if unicodedata.category(c)[0] != 'C')
        
        # 移除前后空格和点
        name = name.strip(' .')
        
        # 限制长度（Windows 最大 255 字符）
        if len(name) > 200:
            name = name[:200]
        
        # 如果文件名为空，使用默认值
        if not name:
            name = "untitled"
        
        return name

    def ensure_directory(self, path: Path) -> Path:
        """
        确保目录存在
        
        Args:
            path: 目录或文件路径
            
        Returns:
            Path: 目录路径
        """
        if path.is_file():
            dir_path = path.parent
        else:
            dir_path = path
        
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def get_relative_path(self, full_path: Path) -> Path:
        """
        获取相对于 Vault 的路径
        
        Args:
            full_path: 完整路径
            
        Returns:
            Path: 相对路径
        """
        try:
            return full_path.relative_to(self.vault_path)
        except ValueError:
            return full_path

    def normalize_path(self, path: str) -> Path:
        """
        标准化路径
        
        Args:
            path: 路径字符串
            
        Returns:
            Path: 标准化后的路径
        """
        # 展开用户目录
        if path.startswith('~'):
            path = Path.home() / path[2:]
        
        return Path(path).resolve()

    def get_backup_path(self, file_path: Path, timestamp: Optional[str] = None) -> Path:
        """
        生成备份文件路径
        
        Args:
            file_path: 原文件路径
            timestamp: 时间戳（可选，默认使用当前时间）
            
        Returns:
            Path: 备份文件路径
        """
        from datetime import datetime
        
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        return file_path.parent / f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"

    def create_gitkeep(self, dir_path: Path) -> None:
        """
        在目录中创建.gitkeep 文件
        
        Args:
            dir_path: 目录路径
        """
        gitkeep = dir_path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    def get_all_markdown_files(self, directory: Path) -> list:
        """
        获取目录下所有 Markdown 文件
        
        Args:
            directory: 目录路径
            
        Returns:
            list: Markdown 文件路径列表
        """
        if not directory.exists():
            return []
        
        return sorted(directory.glob("*.md"))

    def count_books_in_discipline(self, discipline: str) -> int:
        """
        统计学科下的书籍数量
        
        Args:
            discipline: 学科名称
            
        Returns:
            int: 书籍数量
        """
        books_dir = self.vault_path / self.graph_root / discipline / "书籍图谱"
        
        if not books_dir.exists():
            return 0
        
        # 计算.md 文件数量（排除.gitkeep）
        return len([f for f in books_dir.glob("*.md") if not f.name.startswith('.')])
