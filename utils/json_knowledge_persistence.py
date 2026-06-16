"""
JSON知识库持久化模块

基于 AI-reads-books-page-by-page 的 JSON 知识库模式实现。
支持增量缓存、断点续传、跨书籍知识复用。

核心功能：
1. JSON 知识库持久化（替代纯文本缓存）
2. 增量缓存复用（失败重试时100%节省）
3. 跨书籍知识复用（作者、概念等）
4. 结构化查询接口（按书名、作者、概念查询）
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class KnowledgeEntry:
    """知识条目"""
    id: Optional[int]
    book_title: str
    book_author: str
    discipline: str
    entry_type: str  # "chunk_result", "book_graph", "concept", "author_info"
    content: Dict[str, Any]
    content_hash: str
    created_at: datetime
    updated_at: datetime
    source: str  # "llm", "wikipedia", "api", "cache"


class JSONKnowledgeBase:
    """
    JSON知识库持久化管理器

    使用方法：
    ```python
    from utils.json_knowledge_persistence import get_knowledge_base

    # 保存chunk结果
    kb = get_knowledge_base()
    kb.save_chunk_result(
        book_title="君主论",
        chunk_index=0,
        result=chunk_result,
        content_hash="abc123"
    )

    # 查询chunk结果
    cached = kb.get_chunk_result(book_title="君主论", content_hash="abc123")

    # 查询作者信息（跨书籍复用）
    author_info = kb.get_author_info(author_name="马基雅维利")
    ```
    """

    def __init__(self, db_path: str = ".cache/knowledge_base.json"):
        """
        初始化知识库

        Args:
            db_path: 知识库文件路径（JSON格式）
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # SQLite 索引（快速查询）
        self.index_path = self.db_path.with_suffix(".index.db")
        self._init_index()

        # 内存缓存
        self._cache: Dict[str, KnowledgeEntry] = {}

    def _init_index(self):
        """初始化SQLite索引"""
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        # 创建索引表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_title TEXT NOT NULL,
                book_author TEXT,
                discipline TEXT,
                entry_type TEXT NOT NULL,
                content_hash TEXT UNIQUE,
                source TEXT,
                created_at TIMESTAMP,
                json_path TEXT
            )
        """)

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_book_title
            ON knowledge_index(book_title)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_content_hash
            ON knowledge_index(content_hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entry_type
            ON knowledge_index(entry_type)
        """)

        conn.commit()
        conn.close()

    def save_chunk_result(
        self,
        book_title: str,
        chunk_index: int,
        result: Dict[str, Any],
        content_hash: str,
        book_author: str = "",
        discipline: str = ""
    ) -> bool:
        """
        保存chunk分析结果

        Args:
            book_title: 书名
            chunk_index: chunk索引
            result: chunk分析结果
            content_hash: 内容哈希
            book_author: 作者（可选）
            discipline: 学科（可选）

        Returns:
            bool: 是否保存成功
        """
        entry_type = "chunk_result"
        entry_id = f"{book_title}_{chunk_index}"

        entry = KnowledgeEntry(
            id=None,
            book_title=book_title,
            book_author=book_author,
            discipline=discipline,
            entry_type=entry_type,
            content=result,
            content_hash=content_hash,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source="llm"
        )

        # 保存到内存缓存
        self._cache[entry_id] = entry

        # 保存到JSON文件
        try:
            self._save_to_json(entry, entry_id)
            self._add_to_index(entry, entry_id)
            logger.info(f"保存chunk结果: {book_title} - chunk {chunk_index}")
            return True
        except Exception as e:
            logger.error(f"保存chunk结果失败: {e}")
            return False

    def get_chunk_result(
        self,
        book_title: str,
        content_hash: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取chunk分析结果（基于内容哈希）

        Args:
            book_title: 书名
            content_hash: 内容哈希

        Returns:
            Optional[Dict]: chunk结果，不存在返回None
        """
        # 先查索引
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT json_path FROM knowledge_index
            WHERE book_title = ? AND content_hash = ? AND entry_type = 'chunk_result'
        """, (book_title, content_hash))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        json_path = row[0]

        # 从JSON文件读取
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if json_path in data:
                return data[json_path]["content"]
        except Exception as e:
            logger.warning(f"读取chunk结果失败: {e}")

        return None

    def save_author_info(
        self,
        author_name: str,
        author_info: Dict[str, Any],
        source: str = "wikipedia"
    ) -> bool:
        """
        保存作者信息（跨书籍复用）

        Args:
            author_name: 作者名
            author_info: 作者信息
            source: 数据来源（"wikipedia", "llm", "api"）

        Returns:
            bool: 是否保存成功
        """
        entry_id = f"author_{author_name}"

        entry = KnowledgeEntry(
            id=None,
            book_title="",
            book_author=author_name,
            discipline="",
            entry_type="author_info",
            content=author_info,
            content_hash=author_name,  # 作者名作为哈希
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source=source
        )

        self._cache[entry_id] = entry

        try:
            self._save_to_json(entry, entry_id)
            self._add_to_index(entry, entry_id)
            logger.info(f"保存作者信息: {author_name} (来源: {source})")
            return True
        except Exception as e:
            logger.error(f"保存作者信息失败: {e}")
            return False

    def get_author_info(self, author_name: str) -> Optional[Dict[str, Any]]:
        """
        获取作者信息（跨书籍复用）

        Args:
            author_name: 作者名

        Returns:
            Optional[Dict]: 作者信息，不存在返回None
        """
        # 先查索引
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT json_path FROM knowledge_index
            WHERE book_author = ? AND entry_type = 'author_info'
        """, (author_name,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        json_path = row[0]

        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if json_path in data:
                return data[json_path]["content"]
        except Exception as e:
            logger.warning(f"读取作者信息失败: {e}")

        return None

    def save_book_graph(
        self,
        book_title: str,
        book_graph: Dict[str, Any],
        book_author: str = "",
        discipline: str = ""
    ) -> bool:
        """
        保存完整BookGraph（最终输出）

        Args:
            book_title: 书名
            book_graph: BookGraph数据
            book_author: 作者（可选）
            discipline: 学科（可选）

        Returns:
            bool: 是否保存成功
        """
        entry_type = "book_graph"
        entry_id = f"book_{book_title}"

        # 计算内容哈希（基于书名）
        content_hash = f"book_{book_title}"

        entry = KnowledgeEntry(
            id=None,
            book_title=book_title,
            book_author=book_author,
            discipline=discipline,
            entry_type=entry_type,
            content=book_graph,
            content_hash=content_hash,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            source="llm"
        )

        self._cache[entry_id] = entry

        try:
            self._save_to_json(entry, entry_id)
            self._add_to_index(entry, entry_id)
            logger.info(f"保存BookGraph: {book_title}")
            return True
        except Exception as e:
            logger.error(f"保存BookGraph失败: {e}")
            return False

    def get_book_graph(self, book_title: str) -> Optional[Dict[str, Any]]:
        """
        获取完整BookGraph

        Args:
            book_title: 书名

        Returns:
            Optional[Dict]: BookGraph数据，不存在返回None
        """
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT json_path FROM knowledge_index
            WHERE book_title = ? AND entry_type = 'book_graph'
        """, (book_title,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        json_path = row[0]

        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if json_path in data:
                return data[json_path]["content"]
        except Exception as e:
            logger.warning(f"读取BookGraph失败: {e}")

        return None

    def _save_to_json(self, entry: KnowledgeEntry, entry_id: str):
        """保存到JSON文件"""
        # 读取现有数据
        data = {}
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"读取JSON失败，将创建新文件: {e}")

        # 更新数据
        data[entry_id] = {
            "book_title": entry.book_title,
            "book_author": entry.book_author,
            "discipline": entry.discipline,
            "entry_type": entry.entry_type,
            "content": entry.content,
            "content_hash": entry.content_hash,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "source": entry.source
        }

        # 写入文件
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _add_to_index(self, entry: KnowledgeEntry, entry_id: str):
        """添加到SQLite索引"""
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO knowledge_index
            (book_title, book_author, discipline, entry_type, content_hash, source, created_at, json_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.book_title,
            entry.book_author,
            entry.discipline,
            entry.entry_type,
            entry.content_hash,
            entry.source,
            entry.created_at.isoformat(),
            entry_id
        ))

        conn.commit()
        conn.close()

    def get_stats(self) -> Dict[str, int]:
        """获取知识库统计信息"""
        conn = sqlite3.connect(self.index_path)
        cursor = conn.cursor()

        # 总条目数
        cursor.execute("SELECT COUNT(*) FROM knowledge_index")
        total = cursor.fetchone()[0]

        # 按类型统计
        cursor.execute("""
            SELECT entry_type, COUNT(*)
            FROM knowledge_index
            GROUP BY entry_type
        """)
        by_type = dict(cursor.fetchall())

        # 按学科统计
        cursor.execute("""
            SELECT discipline, COUNT(*)
            FROM knowledge_index
            WHERE discipline != ''
            GROUP BY discipline
        """)
        by_discipline = dict(cursor.fetchall())

        conn.close()

        return {
            "total": total,
            "by_type": by_type,
            "by_discipline": by_discipline
        }


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

_kb: Optional[JSONKnowledgeBase] = None
_test_mode = False  # 测试模式标志


def get_knowledge_base(db_path: str = ".cache/knowledge_base.json") -> JSONKnowledgeBase:
    """
    获取知识库单例

    Args:
        db_path: 知识库文件路径

    Returns:
        JSONKnowledgeBase: 知识库实例
    """
    global _kb, _test_mode

    # 测试模式下每次返回新实例（避免测试间互相影响）
    if _test_mode:
        return JSONKnowledgeBase(db_path)

    if _kb is None:
        _kb = JSONKnowledgeBase(db_path)
    return _kb


def enable_test_mode():
    """启用测试模式（每个测试使用独立实例）"""
    global _kb, _test_mode
    _test_mode = True
    _kb = None


def disable_test_mode():
    """禁用测试模式（恢复单例模式）"""
    global _test_mode
    _test_mode = False


def save_chunk_result(
    book_title: str,
    chunk_index: int,
    result: Dict[str, Any],
    content_hash: str,
    **kwargs
) -> bool:
    """
    保存chunk结果的便捷函数

    Args:
        book_title: 书名
        chunk_index: chunk索引
        result: chunk分析结果
        content_hash: 内容哈希
        **kwargs: 其他参数（book_author, discipline）

    Returns:
        bool: 是否保存成功
    """
    kb = get_knowledge_base()
    return kb.save_chunk_result(book_title, chunk_index, result, content_hash, **kwargs)


def get_chunk_result(book_title: str, content_hash: str) -> Optional[Dict[str, Any]]:
    """
    获取chunk结果的便捷函数

    Args:
        book_title: 书名
        content_hash: 内容哈希

    Returns:
        Optional[Dict]: chunk结果
    """
    kb = get_knowledge_base()
    return kb.get_chunk_result(book_title, content_hash)


def save_author_info(author_name: str, author_info: Dict[str, Any], source: str = "wikipedia") -> bool:
    """
    保存作者信息的便捷函数

    Args:
        author_name: 作者名
        author_info: 作者信息
        source: 数据来源

    Returns:
        bool: 是否保存成功
    """
    kb = get_knowledge_base()
    return kb.save_author_info(author_name, author_info, source)


def get_author_info(author_name: str) -> Optional[Dict[str, Any]]:
    """
    获取作者信息的便捷函数

    Args:
        author_name: 作者名

    Returns:
        Optional[Dict]: 作者信息
    """
    kb = get_knowledge_base()
    return kb.get_author_info(author_name)
