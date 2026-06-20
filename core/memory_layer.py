"""
BookGraph-Agent 记忆层高级实现

分层记忆架构：
- 短期记忆（ShortTermMemory）：上下文窗口管理、滑动窗口、摘要压缩
- 长期记忆（LongTermMemory）：向量检索、知识图谱、SQLite 持久化
- 工作记忆（WorkingMemory）：当前任务状态栈、中间结果缓存
"""

import logging
import sqlite3
import json
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time

logger = logging.getLogger("BookGraph-Agent")


@dataclass
class MemoryItem:
    """记忆项"""
    id: str
    content: str
    metadata: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    importance: float = 0.5  # 重要性评分 0-1
    access_count: int = 0  # 访问次数

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'content': self.content,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'importance': self.importance,
            'access_count': self.access_count
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryItem':
        return cls(
            id=data['id'],
            content=data['content'],
            metadata=data['metadata'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            importance=data['importance'],
            access_count=data['access_count']
        )


class ShortTermMemory:
    """短期记忆：上下文窗口管理"""

    def __init__(self, max_tokens: int = 4000, max_items: int = 50):
        """
        初始化短期记忆

        Args:
            max_tokens: 最大 token 数（约等于字符数）
            max_items: 最大记忆项数
        """
        self.max_tokens = max_tokens
        self.max_items = max_items
        self.items: List[MemoryItem] = []
        self._current_tokens = 0

    def add(self, content: str, metadata: Dict = None, importance: float = 0.5):
        """添加记忆项"""
        item_tokens = len(content)

        # 滑动窗口策略：超限时移除最旧的低重要性记忆
        while (self._current_tokens + item_tokens > self.max_tokens or
               len(self.items) >= self.max_items):

            if not self.items:
                break

            # 优先移除低重要性记忆
            self.items.sort(key=lambda x: x.importance)
            removed = self.items.pop(0)
            self._current_tokens -= len(removed.content)

        item = MemoryItem(
            id=self._generate_id(content),
            content=content,
            metadata=metadata or {},
            importance=importance
        )

        self.items.append(item)
        self._current_tokens += item_tokens

        logger.debug(f"短期记忆添加: {item.id[:8]}... ({item_tokens} tokens, 总计 {self._current_tokens}/{self.max_tokens})")

    def get_context(self, max_tokens: int = None) -> str:
        """获取上下文（按重要性排序）"""
        max_tokens = max_tokens or self.max_tokens

        # 按重要性降序排序
        sorted_items = sorted(self.items, key=lambda x: x.importance, reverse=True)

        context_parts = []
        current_tokens = 0

        for item in sorted_items:
            item_tokens = len(item.content)
            if current_tokens + item_tokens > max_tokens:
                break

            context_parts.append(item.content)
            current_tokens += item_tokens
            item.access_count += 1

        return "\n\n".join(context_parts)

    def compress(self, llm_client=None) -> str:
        """压缩上下文（生成摘要）"""
        if not self.items:
            return ""

        # 简单压缩：提取高重要性记忆
        high_importance = [item for item in self.items if item.importance >= 0.7]

        if not high_importance:
            # 如果没有高重要性记忆，保留最近 5 条
            high_importance = self.items[-5:]

        summary = f"[摘要] {len(self.items)} 条记忆中保留 {len(high_importance)} 条关键记忆:\n"
        summary += "\n".join([f"- {item.content[:100]}..." for item in high_importance[:10]])

        # 清空当前记忆，添加摘要
        self.items.clear()
        self._current_tokens = 0
        self.add(summary, metadata={'type': 'summary'}, importance=0.9)

        return summary

    def clear(self):
        """清空短期记忆"""
        self.items.clear()
        self._current_tokens = 0

    def _generate_id(self, content: str) -> str:
        """生成记忆 ID（基于内容哈希）"""
        return hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()


class LongTermMemory:
    """长期记忆：向量检索 + SQLite 持久化"""

    def __init__(self, db_path: str = ".cache/long_term_memory.db"):
        """
        初始化长期记忆

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self._init_db()

        # 尝试初始化向量检索（可选依赖）
        self.vector_store = None
        try:
            # 未来可集成 LanceDB/Chroma/Pinecone
            pass
        except Exception:
            logger.info("向量检索未启用，使用 SQLite 文本搜索")

    def _init_db(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)

        # 创建全文搜索索引
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
            USING FTS5(content, metadata)
        """)

        conn.commit()
        conn.close()

    def save(self, item: MemoryItem):
        """保存记忆项"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO long_term_memory
            (id, content, metadata, importance, access_count)
            VALUES (?, ?, ?, ?, ?)
        """, (
            item.id,
            item.content,
            json.dumps(item.metadata),
            item.importance,
            item.access_count
        ))

        # 同步到全文搜索索引
        cursor.execute("""
            INSERT INTO memory_fts (rowid, content, metadata)
            VALUES ((SELECT rowid FROM long_term_memory WHERE id = ?), ?, ?)
        """, (item.id, item.content, json.dumps(item.metadata)))

        conn.commit()
        conn.close()

        logger.debug(f"长期记忆保存: {item.id[:8]}...")

    def recall(self, query: str, top_k: int = 5) -> List[MemoryItem]:
        """召回相关记忆（文本搜索）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 使用全文搜索
        cursor.execute("""
            SELECT id, content, metadata, importance, access_count
            FROM long_term_memory
            WHERE id IN (
                SELECT rowid FROM memory_fts WHERE memory_fts MATCH ?
            )
            ORDER BY importance DESC
            LIMIT ?
        """, (query, top_k))

        results = []
        for row in cursor.fetchall():
            item = MemoryItem(
                id=row[0],
                content=row[1],
                metadata=json.loads(row[2]),
                importance=row[3],
                access_count=row[4]
            )
            results.append(item)

            # 增加访问计数
            cursor.execute(
                "UPDATE long_term_memory SET access_count = access_count + 1 WHERE id = ?",
                (item.id,)
            )

        conn.commit()
        conn.close()

        logger.debug(f"长期记忆召回: {len(results)} 条相关记忆")
        return results

    def recall_by_metadata(self, metadata_key: str, metadata_value: Any, top_k: int = 10) -> List[MemoryItem]:
        """按元数据召回记忆"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, content, metadata, importance, access_count
            FROM long_term_memory
            WHERE json_extract(metadata, ?) = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f'$.{metadata_key}', metadata_value, top_k))

        results = []
        for row in cursor.fetchall():
            item = MemoryItem(
                id=row[0],
                content=row[1],
                metadata=json.loads(row[2]),
                importance=row[3],
                access_count=row[4]
            )
            results.append(item)

        conn.close()
        return results


class WorkingMemory:
    """工作记忆：当前任务状态栈"""

    def __init__(self, max_stack_size: int = 10):
        """
        初始化工作记忆

        Args:
            max_stack_size: 最大栈大小
        """
        self.max_stack_size = max_stack_size
        self.stack: List[Dict] = []
        self.cache: Dict[str, Any] = {}  # 中间结果缓存

    def push(self, state: Dict):
        """压入状态"""
        if len(self.stack) >= self.max_stack_size:
            # 移除最旧的状态
            self.stack.pop(0)

        self.stack.append({
            'state': state,
            'timestamp': datetime.now().isoformat()
        })

        logger.debug(f"工作记忆压入: {state.get('phase', 'unknown')}")

    def pop(self) -> Optional[Dict]:
        """弹出状态"""
        if not self.stack:
            return None

        item = self.stack.pop()
        logger.debug(f"工作记忆弹出: {item['state'].get('phase', 'unknown')}")
        return item['state']

    def peek(self) -> Optional[Dict]:
        """查看栈顶状态"""
        if not self.stack:
            return None

        return self.stack[-1]['state']

    def cache_result(self, key: str, result: Any):
        """缓存中间结果"""
        self.cache[key] = {
            'result': result,
            'timestamp': datetime.now().isoformat()
        }

    def get_cached_result(self, key: str) -> Optional[Any]:
        """获取缓存结果"""
        cached = self.cache.get(key)
        if cached:
            logger.debug(f"工作记忆缓存命中: {key}")
            return cached['result']
        return None

    def clear(self):
        """清空工作记忆"""
        self.stack.clear()
        self.cache.clear()


class HybridMemoryManager:
    """混合记忆管理器：整合三层记忆"""

    def __init__(self, config: Dict = None):
        """
        初始化混合记忆管理器

        Args:
            config: 配置字典
        """
        config = config or {}

        self.short_term = ShortTermMemory(
            max_tokens=config.get('short_term_max_tokens', 4000),
            max_items=config.get('short_term_max_items', 50)
        )

        self.long_term = LongTermMemory(
            db_path=config.get('long_term_db_path', '.cache/long_term_memory.db')
        )

        self.working = WorkingMemory(
            max_stack_size=config.get('working_max_stack_size', 10)
        )

    def remember(self, content: str, metadata: Dict = None, importance: float = 0.5, persist: bool = False):
        """
        记忆内容

        Args:
            content: 记忆内容
            metadata: 元数据
            importance: 重要性评分 0-1
            persist: 是否持久化到长期记忆
        """
        # 添加到短期记忆
        self.short_term.add(content, metadata, importance)

        # 如果重要或明确要求持久化，保存到长期记忆
        if persist or importance >= 0.8:
            item = MemoryItem(
                id=self._generate_id(content),
                content=content,
                metadata=metadata or {},
                importance=importance
            )
            self.long_term.save(item)

    def recall(self, query: str, top_k: int = 5, use_long_term: bool = True) -> List[str]:
        """
        召回相关记忆

        Args:
            query: 查询字符串
            top_k: 返回数量
            use_long_term: 是否搜索长期记忆

        Returns:
            List[str]: 相关记忆内容列表
        """
        results = []

        # 先从短期记忆获取
        short_term_context = self.short_term.get_context(max_tokens=1000)
        if short_term_context:
            results.append(short_term_context)

        # 如果需要，从长期记忆检索
        if use_long_term:
            long_term_items = self.long_term.recall(query, top_k=top_k)
            results.extend([item.content for item in long_term_items])

        return results[:top_k]

    def push_state(self, state: Dict):
        """压入工作记忆状态"""
        self.working.push(state)

    def pop_state(self) -> Optional[Dict]:
        """弹出工作记忆状态"""
        return self.working.pop()

    def cache_intermediate_result(self, key: str, result: Any):
        """缓存中间结果"""
        self.working.cache_result(key, result)

    def get_cached_result(self, key: str) -> Optional[Any]:
        """获取缓存结果"""
        return self.working.get_cached_result(key)

    def compress_context(self):
        """压缩短期记忆上下文"""
        return self.short_term.compress()

    def clear_all(self):
        """清空所有记忆"""
        self.short_term.clear()
        self.working.clear()

    def _generate_id(self, content: str) -> str:
        """生成记忆 ID"""
        return hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()
