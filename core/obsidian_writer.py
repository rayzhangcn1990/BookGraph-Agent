"""
Obsidian Writer - Obsidian 文件写入模块

负责将知识图谱写入 Obsidian Vault，管理目录结构和文件备份。
"""

import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import shutil
import os
import re

from schemas.book_graph_schema import BookGraph, DisciplineType

logger = logging.getLogger("BookGraph-Agent")


class ObsidianWriter:
    """
    Obsidian 写入器
    
    功能：
    - 写入书籍知识图谱
    - 写入学科知识图谱
    - 自动创建目录结构
    - 文件备份管理
    - 读取现有图谱
    """

    def __init__(self, config: Dict = None):
        """
        初始化写入器
        
        Args:
            config: 配置字典
                - vault_path: Obsidian Vault 路径
                - graph_root: 图谱根目录
                - discipline_paths: 学科路径映射
                - subdirectories: 子目录配置
        """
        self.config = config or {}
        self.vault_path = Path(self._resolve_path_value(self.config.get('vault_path', '')))
        self.graph_root = self.config.get('graph_root', '📚 知识图谱')
        self.discipline_paths = self.config.get('discipline_paths', {})
        self.subdirectories = self.config.get('subdirectories', {
            'books': '书籍图谱',
            'discipline': '学科图谱',
            'concepts': '概念词汇库',
            'beginner': '入门指南',
        })
        
        # 验证 Vault 路径
        if not self.vault_path.exists():
            logger.warning(f"⚠️ Obsidian Vault 路径不存在：{self.vault_path}")

    def write_book_graph(
        self,
        book_graph: BookGraph,
        markdown_content: str,
        source_book_path: Optional[Path] = None
    ) -> Path:
        """
        写入书籍知识图谱

        Args:
            book_graph: 书籍知识图谱对象
            markdown_content: Markdown 内容
            source_book_path: 源书籍路径（用于推断输出目录）

        Returns:
            Path: 写入文件的绝对路径
        """
        # 🔑 新增：根据源书籍路径推断输出目录
        if source_book_path:
            book_path_parts = source_book_path.parent.parts
            if len(book_path_parts) >= 2:
                # 获取上级文件夹名称和当前文件夹名称
                parent_folder = book_path_parts[-2] if len(book_path_parts) >= 2 else ""
                current_folder = book_path_parts[-1]
                # 构建输出目录：~/文稿/知识体系/📚 知识图谱/{上级文件夹}/{当前文件夹}/书籍图谱
                books_dir = self.vault_path / self.graph_root / parent_folder / current_folder / self.subdirectories['books']
            else:
                # 回退：使用学科路径
                discipline = book_graph.metadata.discipline.value
                discipline_path = self._get_discipline_path(discipline)
                books_dir = self.vault_path / discipline_path / self.subdirectories['books']
        else:
            # 原有逻辑：使用学科路径
            discipline = book_graph.metadata.discipline.value
            discipline_path = self._get_discipline_path(discipline)
            books_dir = self.vault_path / discipline_path / self.subdirectories['books']

        books_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成安全的文件名
        book_title = self._sanitize_filename(book_graph.metadata.title)
        file_path = books_dir / f"{book_title}.md"
        
        # 🔑 原子写入：先写临时文件，再rename
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            suffix='.md',
            dir=books_dir,
            delete=False
        )

        try:
            temp_file.write(markdown_content)
            temp_file.close()

            # 删除旧文件（如果存在）
            if file_path.exists():
                file_path.unlink()

            # Rename临时文件为正式文件
            Path(temp_file.name).rename(file_path)
            logger.info(f"✅ 书籍图谱已写入：{file_path}")

        except Exception as e:
            # 写入失败，清理临时文件
            Path(temp_file.name).unlink(missing_ok=True)
            raise e
        return file_path.resolve()


    def update_section(
        self,
        discipline: str,
        book_title: str,
        section_name: str,
        section_content: str
    ) -> Path:
        """
        增量更新书籍图谱的某个章节
        
        Args:
            discipline: 学科名称  
            book_title: 书籍标题
            section_name: 要更新的章节名称
            section_content: 章节内容（Markdown格式）
            
        Returns:
            Path: 更新后的文件路径
        """
        import re
        
        discipline_path = self._get_discipline_path(discipline)
        books_dir = self.vault_path / discipline_path / self.subdirectories["books"]
        books_dir.mkdir(parents=True, exist_ok=True)
        
        safe_title = self._sanitize_filename(book_title)
        file_path = books_dir / f"{safe_title}.md"
        
        section_headers = {
            "时代背景": "# 📜 一、时代背景",
            "章节结构": "# 📑 二、章节结构总览",
            "核心概念": "# 💡 三、核心概念",
            "关键洞见": "# 🔍 四、关键洞见",
            "关键案例": "# 📚 五、关键案例",
            "金句萃取": "# ✨ 六、金句萃取",
            "批判性解读": "# 🤔 七、批判性解读",
        }
        
        target_header = section_headers.get(section_name, f"## {section_name}")
        
        if not file_path.exists():
            skeleton = "---\n" + f"title: {book_title}\ndiscipline: {discipline}\ncreated: {datetime.now().strftime('%Y-%m-%d')}\ntype: book-graph\n---\n\n" + f"{target_header}\n\n{section_content}\n\n---\n\n*最后更新*: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            file_path.write_text(skeleton.replace("\n", "\n"), encoding="utf-8")
            logger.info(f"✅ 创建骨架 → {file_path.name}")
            return file_path.resolve()
        
        content = file_path.read_text(encoding="utf-8")

        # 找到章节并替换（匹配一级标题格式）
        # 骨架格式: "# 📜 一、时代背景\n\ncontent\n\n---\n\n"
        pattern = target_header + r"\n\n(.*?)(\n---\n\n# |$)"
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            # 替换现有内容
            start = match.start(1)
            end = match.end(1)
            new_content = content[:start] + section_content + content[end:]
            
            # 更新时间
            new_content = re.sub(r"\*最后更新\*: .*", f"*最后更新*: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_content)
            
            file_path.write_text(new_content, encoding="utf-8")
            logger.info(f"✅ 更新 [{section_name}] → {file_path.name}")
        
        return file_path.resolve()

    def write_discipline_graph(
        self, 
        discipline: str, 
        content: str
    ) -> Path:
        """
        写入学科知识图谱
        
        Args:
            discipline: 学科名称
            content: Markdown 内容
            
        Returns:
            Path: 写入文件的绝对路径
        """
        # 获取学科路径
        discipline_path = self._get_discipline_path(discipline)
        
        # 构建文件路径
        discipline_dir = self.vault_path / discipline_path / self.subdirectories['discipline']
        discipline_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = discipline_dir / f"{discipline}学科图谱.md"

        # 如果文件已存在，创建备份
        if file_path.exists():
            self._create_backup(file_path)

        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"✅ 学科图谱已写入：{file_path}")
        return file_path.resolve()

    def ensure_discipline_structure(self, discipline: str) -> None:
        """
        确保学科目录结构存在
        
        Args:
            discipline: 学科名称
        """
        discipline_path = self._get_discipline_path(discipline)
        base_dir = self.vault_path / discipline_path
        
        # 创建子目录
        for subdir in self.subdirectories.values():
            dir_path = base_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # 创建.gitkeep 文件
            gitkeep = dir_path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.touch()

        logger.info(f"✅ 学科目录结构已确保：{discipline_path}")

    def read_existing_discipline_graph(self, discipline: str) -> Optional[str]:
        """
        读取已存在的学科图谱内容
        
        Args:
            discipline: 学科名称
            
        Returns:
            Optional[str]: 图谱内容，不存在则返回 None
        """
        discipline_path = self._get_discipline_path(discipline)
        file_path = self.vault_path / discipline_path / self.subdirectories['discipline'] / f"{discipline}学科图谱.md"
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"⚠️ 读取学科图谱失败：{e}")
            return None

    def get_all_books_in_discipline(self, discipline: str) -> List[str]:
        """
        获取学科下所有书籍图谱文件名
        
        Args:
            discipline: 学科名称
            
        Returns:
            List[str]: 书籍文件名列表（不含扩展名）
        """
        discipline_path = self._get_discipline_path(discipline)
        books_dir = self.vault_path / discipline_path / self.subdirectories['books']
        
        if not books_dir.exists():
            return []
        
        books = []
        for file in books_dir.glob("*.md"):
            if not file.name.startswith('.'):
                books.append(file.stem)
        
        return sorted(books)

    def _resolve_path_value(self, value: str) -> str:
        """解析配置中的 ${VAR_NAME} 环境变量引用。"""
        if not isinstance(value, str):
            return value

        def replace_env_var(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, '')

        return re.sub(r'\$\{([^}]+)\}', replace_env_var, value)

    def _get_discipline_path(self, discipline: str) -> Path:
        """
        获取学科在 Vault 中的相对路径
        
        Args:
            discipline: 学科名称
            
        Returns:
            Path: 相对路径
        """
        # 从配置中查找
        if discipline in self.discipline_paths:
            return Path(self.discipline_paths[discipline])
        
        # 默认路径
        return Path(self.graph_root) / discipline

    def _sanitize_filename(self, name: str, max_length: int = 180) -> str:
        """
        生成安全的文件名（优化版：保持与书籍名称一致性）

        Args:
            name: 原始名称
            max_length: 最大文件名长度（默认 180，扩展以保持完整性）

        Returns:
            str: 安全的文件名
        """
        # ponytail: 优先保持书名完整性（而非截断）

        # 移除或替换非法字符
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            name = name.replace(char, '_')

        # 移除前后空格
        name = name.strip()

        # 🔑 优化：仅在超长时添加哈希后缀（而非截断）
        # macOS 文件名限制：255 bytes（UTF-8编码）
        if len(name.encode('utf-8')) > max_length:
            import hashlib
            name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
            # 截断到安全长度（保留哈希后缀空间）
            safe_len = max_length - 9
            encoded = name.encode('utf-8')[:safe_len]
            name = encoded.decode('utf-8', errors='ignore').strip(' ._') + f"_{name_hash}"

        return name

    def _create_backup(self, file_path: Path) -> Path:
        """
        创建文件备份
        
        Args:
            file_path: 原文件路径
            
        Returns:
            Path: 备份文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_backup_{timestamp}.md"
        backup_path = file_path.parent / backup_name
        
        shutil.copy2(file_path, backup_path)
        return backup_path

    def read_book_graph(self, discipline: str, book_title: str) -> Optional[str]:
        """
        读取已有的书籍图谱
        
        Args:
            discipline: 学科名称
            book_title: 书名
            
        Returns:
            Optional[str]: 图谱内容，不存在则返回 None
        """
        discipline_path = self._get_discipline_path(discipline)
        file_path = (
            self.vault_path / 
            discipline_path / 
            self.subdirectories['books'] / 
            f"{self._sanitize_filename(book_title)}.md"
        )
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"⚠️ 读取书籍图谱失败：{e}")
            return None

    def delete_book_graph(self, discipline: str, book_title: str) -> bool:
        """
        删除书籍图谱
        
        Args:
            discipline: 学科名称
            book_title: 书名
            
        Returns:
            bool: 是否成功删除
        """
        discipline_path = self._get_discipline_path(discipline)
        file_path = (
            self.vault_path / 
            discipline_path / 
            self.subdirectories['books'] / 
            f"{self._sanitize_filename(book_title)}.md"
        )
        
        if not file_path.exists():
            return False
        
        try:
            # 创建备份后删除
            self._create_backup(file_path)
            file_path.unlink()
            logger.info(f"✅ 已删除书籍图谱：{book_title}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ 删除书籍图谱失败：{e}")
            return False

    def get_vault_stats(self) -> Dict:
        """
        获取 Vault 统计信息
        
        Returns:
            Dict: 统计信息
        """
        stats = {
            'total_books': 0,
            'total_disciplines': 0,
            'books_by_discipline': {},
        }
        
        if not self.vault_path.exists():
            return stats
        
        # 遍历学科目录
        graph_root = self.vault_path / self.graph_root
        if not graph_root.exists():
            return stats
        
        for discipline_dir in graph_root.iterdir():
            if not discipline_dir.is_dir() or discipline_dir.name.startswith('.'):
                continue
            
            discipline = discipline_dir.name
            books_dir = discipline_dir / self.subdirectories['books']
            
            if books_dir.exists():
                # 只统计 .md 文件，排除隐藏文件和 .gitkeep
                md_files = [f for f in books_dir.glob("*.md") if not f.name.startswith('.')]
                book_count = len(md_files)
                stats['books_by_discipline'][discipline] = book_count
                stats['total_books'] += book_count
                stats['total_disciplines'] += 1
        
        return stats
