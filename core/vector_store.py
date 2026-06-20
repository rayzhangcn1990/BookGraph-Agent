"""
BookGraph-Agent LanceDB 向量检索集成

提供长期记忆的语义检索能力，支持：
- 向量存储（sentence-transformers 嵌入）
- 相似度检索（LanceDB 向量搜索）
- 混合检索（向量 + 文本 + 元数据）
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from pathlib import Path
import json
import time

logger = logging.getLogger("BookGraph-Agent")

# 尝试导入向量检索依赖
try:
    import lancedb
    from lancedb.embeddings import EmbeddingFunctionRegistry, with_embeddings
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False
    logger.warning("LanceDB 未安装，向量检索功能不可用")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers 未安装，嵌入生成功能不可用")


@dataclass
class VectorMemoryItem:
    """向量记忆项"""
    id: str
    content: str
    metadata: Dict
    embedding: Optional[List[float]] = None
    timestamp: float = time.time()
    importance: float = 0.5


class LanceDBVectorStore:
    """LanceDB 向量存储管理器"""

    def __init__(self, db_path: str = ".cache/vector_memory.lancedb", embedding_model: str = "all-MiniLM-L6-v2"):
        """
        初始化向量存储

        Args:
            db_path: LanceDB 数据库路径
            embedding_model: 嵌入模型名称（sentence-transformers）
        """
        self.db_path = db_path
        self.embedding_model_name = embedding_model

        # 初始化数据库和嵌入模型
        self.db = None
        self.table = None
        self.embedding_model = None

        if LANCEDB_AVAILABLE and EMBEDDINGS_AVAILABLE:
            self._init_db()
            self._init_embedding_model()
        else:
            logger.warning("向量检索初始化失败，依赖未安装")

    def _init_db(self):
        """初始化 LanceDB 数据库"""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db = lancedb.connect(self.db_path)

            # 创建或获取表
            table_name = "memory_vectors"

            if table_name in self.db.table_names():
                self.table = self.db.open_table(table_name)
                logger.info(f"LanceDB 表已打开: {table_name} ({self.table.count_rows()} 行)")
            else:
                # 创建空表（schema 将在首次插入时确定）
                logger.info(f"LanceDB 表已创建: {table_name}")
                self.table = None  # 首次插入时创建

        except Exception as e:
            logger.error(f"LanceDB 初始化失败: {e}")
            self.db = None

    def _init_embedding_model(self):
        """初始化嵌入模型"""
        try:
            self.embedding_model = SentenceTransformer(self.embedding_model_name)
            logger.info(f"嵌入模型已加载: {self.embedding_model_name}")
        except Exception as e:
            logger.error(f"嵌入模型加载失败: {e}")
            self.embedding_model = None

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """生成文本嵌入向量"""
        if not self.embedding_model:
            return None

        try:
            embedding = self.embedding_model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"嵌入生成失败: {e}")
            return None

    def save(self, item: VectorMemoryItem) -> bool:
        """保存向量记忆项"""
        if not self.db or not self.embedding_model:
            logger.warning("向量存储未初始化，跳过保存")
            return False

        try:
            # 生成嵌入（如果未提供）
            if not item.embedding:
                item.embedding = self.generate_embedding(item.content)

            if not item.embedding:
                return False

            # 构造数据记录
            data = {
                "id": item.id,
                "content": item.content,
                "metadata": json.dumps(item.metadata),
                "embedding": item.embedding,
                "timestamp": item.timestamp,
                "importance": item.importance
            }

            # 首次插入时创建表
            if not self.table:
                import pyarrow as pa

                schema = pa.schema([
                    pa.field("id", pa.string()),
                    pa.field("content", pa.string()),
                    pa.field("metadata", pa.string()),
                    pa.field("embedding", pa.list_(pa.float32(), list_size=len(item.embedding))),
                    pa.field("timestamp", pa.float64()),
                    pa.field("importance", pa.float64())
                ])

                self.table = self.db.create_table("memory_vectors", schema=schema)

            # 插入数据
            self.table.add([data])
            logger.debug(f"向量记忆保存: {item.id[:8]}...")

            return True

        except Exception as e:
            logger.error(f"向量记忆保存失败: {e}")
            return False

    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.7
    ) -> List[Tuple[VectorMemoryItem, float]]:
        """
        搜索相似记忆

        Args:
            query: 查询文本
            top_k: 返回数量
            min_similarity: 最小相似度阈值

        Returns:
            List[Tuple[VectorMemoryItem, float]]: (记忆项, 相似度) 列表
        """
        if not self.table or not self.embedding_model:
            logger.warning("向量检索未初始化")
            return []

        try:
            # 生成查询嵌入
            query_embedding = self.generate_embedding(query)

            if not query_embedding:
                return []

            # LanceDB 向量搜索
            results = self.table.search(query_embedding).limit(top_k).to_list()

            # 转换结果
            similar_items = []

            for result in results:
                # LanceDB 返回的距离需要转换为相似度（1 - distance）
                similarity = 1.0 - result.get("_distance", 0.0)

                if similarity < min_similarity:
                    continue

                item = VectorMemoryItem(
                    id=result["id"],
                    content=result["content"],
                    metadata=json.loads(result["metadata"]),
                    embedding=result.get("embedding"),
                    timestamp=result["timestamp"],
                    importance=result["importance"]
                )

                similar_items.append((item, similarity))

            logger.debug(f"向量检索完成: {len(similar_items)} 条相似记忆")
            return similar_items

        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    def search_by_metadata(
        self,
        metadata_key: str,
        metadata_value: Any,
        top_k: int = 10
    ) -> List[VectorMemoryItem]:
        """按元数据搜索记忆"""
        if not self.table:
            return []

        try:
            # LanceDB SQL 查询
            results = self.table.search().where(
                f"json_extract(metadata, '$.{metadata_key}') = '{metadata_value}'"
            ).limit(top_k).to_list()

            items = []
            for result in results:
                item = VectorMemoryItem(
                    id=result["id"],
                    content=result["content"],
                    metadata=json.loads(result["metadata"]),
                    timestamp=result["timestamp"],
                    importance=result["importance"]
                )
                items.append(item)

            return items

        except Exception as e:
            logger.error(f"元数据检索失败: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        metadata_filters: Dict = None,
        top_k: int = 5
    ) -> List[Tuple[VectorMemoryItem, float]]:
        """
        混合检索（向量 + 元数据）

        Args:
            query: 查询文本
            metadata_filters: 元数据过滤条件
            top_k: 返回数量

        Returns:
            List[Tuple[VectorMemoryItem, float]]: 检索结果
        """
        if not self.table:
            return []

        try:
            # 生成查询嵌入
            query_embedding = self.generate_embedding(query)

            if not query_embedding:
                return []

            # 构造 LanceDB 查询
            search = self.table.search(query_embedding).limit(top_k)

            # 添加元数据过滤
            if metadata_filters:
                for key, value in metadata_filters.items():
                    search = search.where(f"json_extract(metadata, '$.{key}') = '{value}'")

            results = search.to_list()

            # 转换结果
            items = []
            for result in results:
                similarity = 1.0 - result.get("_distance", 0.0)
                item = VectorMemoryItem(
                    id=result["id"],
                    content=result["content"],
                    metadata=json.loads(result["metadata"]),
                    timestamp=result["timestamp"],
                    importance=result["importance"]
                )
                items.append((item, similarity))

            return items

        except Exception as e:
            logger.error(f"混合检索失败: {e}")
            return []

    def get_stats(self) -> Dict:
        """获取向量存储统计信息"""
        if not self.table:
            return {"status": "unavailable"}

        try:
            return {
                "status": "available",
                "table_name": "memory_vectors",
                "total_items": self.table.count_rows(),
                "embedding_model": self.embedding_model_name,
                "db_path": self.db_path
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def clear(self):
        """清空向量存储"""
        if self.db and "memory_vectors" in self.db.table_names():
            try:
                self.db.drop_table("memory_vectors")
                self.table = None
                logger.info("向量存储已清空")
            except Exception as e:
                logger.error(f"清空向量存储失败: {e}")


class HybridVectorMemoryManager:
    """混合向量记忆管理器（整合 LanceDB + SQLite）"""

    def __init__(self, config: Dict = None):
        """
        初始化混合记忆管理器

        Args:
            config: 配置字典
        """
        config = config or {}

        # SQLite 长期记忆（基础）
        from core.memory_layer import LongTermMemory
        self.sqlite_memory = LongTermMemory(
            db_path=config.get('sqlite_db_path', '.cache/long_term_memory.db')
        )

        # LanceDB 向量记忆（增强）
        self.vector_memory = LanceDBVectorStore(
            db_path=config.get('lancedb_path', '.cache/vector_memory.lancedb'),
            embedding_model=config.get('embedding_model', 'all-MiniLM-L6-v2')
        )

    def save_memory(self, content: str, metadata: Dict, importance: float = 0.5) -> bool:
        """
        保存记忆（双重存储）

        Args:
            content: 记忆内容
            metadata: 元数据
            importance: 重要性评分

        Returns:
            bool: 是否成功
        """
        from core.memory_layer import MemoryItem
        import hashlib

        # 生成 ID
        memory_id = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()

        # SQLite 存储（基础）
        sqlite_item = MemoryItem(
            id=memory_id,
            content=content,
            metadata=metadata,
            importance=importance
        )
        self.sqlite_memory.save(sqlite_item)

        # LanceDB 存储（向量增强）
        vector_item = VectorMemoryItem(
            id=memory_id,
            content=content,
            metadata=metadata,
            importance=importance
        )
        vector_saved = self.vector_memory.save(vector_item)

        # 至少 SQLite 成功即可
        return True

    def recall_similar(
        self,
        query: str,
        top_k: int = 5,
        use_vector: bool = True
    ) -> List[Tuple[str, float]]:
        """
        召回相似记忆

        Args:
            query: 查询文本
            top_k: 返回数量
            use_vector: 是否使用向量检索

        Returns:
            List[Tuple[str, float]]: (记忆内容, 相似度) 列表
        """
        results = []

        # 优先使用向量检索
        if use_vector and self.vector_memory.table:
            vector_results = self.vector_memory.search_similar(query, top_k)
            results.extend([(item.content, similarity) for item, similarity in vector_results])

        # 如果向量检索结果不足，补充文本检索
        if len(results) < top_k:
            text_results = self.sqlite_memory.recall(query, top_k - len(results))
            # 文本检索结果相似度设为默认值
            results.extend([(item.content, 0.5) for item in text_results])

        return results[:top_k]

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "sqlite": "available",
            "lancedb": self.vector_memory.get_stats()
        }