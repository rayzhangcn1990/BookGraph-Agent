"""
参考 nano-graphrag 优化异步架构

关键学习点：
1. 全局异步客户端单例（避免重复初始化）
2. asyncio.gather 并发控制
3. limit_async_func_call 装饰器（Semaphore 限流）
4. NetworkX GraphML 序列化
5. 增量插入（MD5 哈希去重）

参考：https://github.com/gusye1234/nano-graphrag
"""

import asyncio
import hashlib
import json
import logging
import os
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import networkx as nx

logger = logging.getLogger("BookGraph-Agent")


# ═══════════════════════════════════════════════════════════
# 1. 异步客户端单例模式（参考 nano-graphrag/_llm.py）
# ═══════════════════════════════════════════════════════════

_global_async_openai_client = None
_global_async_anthropic_client = None


def get_global_async_openai_client():
    """全局 AsyncOpenAI 客户端单例"""
    global _global_async_openai_client
    if _global_async_openai_client is None:
        from openai import AsyncOpenAI
        _global_async_openai_client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    return _global_async_openai_client


def get_global_async_anthropic_client():
    """全局 AsyncAnthropic 客户端单例"""
    global _global_async_anthropic_client
    if _global_async_anthropic_client is None:
        from anthropic import AsyncAnthropic
        _global_async_anthropic_client = AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
        )
    return _global_async_anthropic_client


# ═══════════════════════════════════════════════════════════
# 2. 并发限流装饰器（参考 nano-graphrag/_utils.py）
# ═══════════════════════════════════════════════════════════

def limit_async_func_call(max_concurrent: int = 16):
    """
    限制异步函数并发数的装饰器

    用法：
        @limit_async_func_call(8)
        async def my_async_function():
            ...

    参考：nano-graphrag 使用此模式限制 LLM 调用并发
    """
    def decorator(func: Callable) -> Callable:
        semaphore = asyncio.Semaphore(max_concurrent)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with semaphore:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════
# 3. NetworkX 图存储（参考 nano-graphrag/_storage/gdb_networkx.py）
# ═══════════════════════════════════════════════════════════

class NetworkXGraphStorage:
    """
    NetworkX 图存储器

    功能：
    - 图的持久化（GraphML 格式）
    - 节点/边的 CRUD 操作
    - 社区检测（Leiden 算法）
    - 增量更新

    参考：nano-graphrag/gdb_networkx.py
    """

    def __init__(self, working_dir: str, namespace: str = "knowledge_graph"):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.namespace = namespace
        self._graph_file = self.working_dir / f"{namespace}.graphml"

        # 加载已有图
        self._graph = self._load_graph()

    def _load_graph(self) -> nx.Graph:
        """加载已有图"""
        if self._graph_file.exists():
            try:
                graph = nx.read_graphml(str(self._graph_file))
                logger.info(f"📂 加载图: {graph.number_of_nodes()} 节点, {graph.number_of_edges()} 边")
                return graph
            except Exception as e:
                logger.warning(f"⚠️ 加载图失败: {e}")
        return nx.Graph()

    async def save_graph(self):
        """保存图到文件"""
        try:
            nx.write_graphml(self._graph, str(self._graph_file))
            logger.info(f"💾 保存图: {self._graph.number_of_nodes()} 节点, {self._graph.number_of_edges()} 边")
        except Exception as e:
            logger.error(f"❌ 保存图失败: {e}")

    async def upsert_node(self, node_id: str, node_data: Dict[str, Any]):
        """插入或更新节点"""
        self._graph.add_node(node_id, **node_data)

    async def upsert_edge(self, source: str, target: str, edge_data: Dict[str, Any]):
        """插入或更新边"""
        self._graph.add_edge(source, target, **edge_data)

    async def get_node(self, node_id: str) -> Optional[Dict]:
        """获取节点数据"""
        return self._graph.nodes.get(node_id)

    async def get_edge(self, source: str, target: str) -> Optional[Dict]:
        """获取边数据"""
        return self._graph.edges.get((source, target))

    async def has_node(self, node_id: str) -> bool:
        """检查节点是否存在"""
        return self._graph.has_node(node_id)

    async def has_edge(self, source: str, target: str) -> bool:
        """检查边是否存在"""
        return self._graph.has_edge(source, target)

    async def get_node_edges(self, node_id: str) -> List[Tuple[str, str]]:
        """获取节点的所有边"""
        if self._graph.has_node(node_id):
            return list(self._graph.edges(node_id))
        return []

    async def get_neighbors(self, node_id: str) -> List[str]:
        """获取节点的所有邻居"""
        if self._graph.has_node(node_id):
            return list(self._graph.neighbors(node_id))
        return []

    def detect_communities_leiden(self) -> Dict[str, int]:
        """
        使用 Leiden 算法检测社区

        返回：{node_id: community_id}
        """
        try:
            from community import best_partition

            partition = best_partition(self._graph)
            logger.info(f"🔍 检测到 {len(set(partition.values()))} 个社区")
            return partition
        except ImportError:
            logger.warning("⚠️ python-louvain 未安装，无法检测社区")
            return {}

    def get_node_degree(self, node_id: str) -> int:
        """获取节点度数"""
        return self._graph.degree(node_id) if self._graph.has_node(node_id) else 0

    def get_bridge_nodes(self, min_communities: int = 3) -> List[str]:
        """
        检测桥节点（连接多个社区的节点）

        参考：BookGraph-Agent 原有实现
        """
        communities = self.detect_communities_leiden()

        bridge_nodes = []
        for node in self._graph.nodes():
            neighbor_communities = set()
            for neighbor in self._graph.neighbors(node):
                if neighbor in communities:
                    neighbor_communities.add(communities[neighbor])

            if len(neighbor_communities) >= min_communities:
                bridge_nodes.append(node)

        logger.info(f"🌉 检测到 {len(bridge_nodes)} 个桥节点")
        return bridge_nodes


# ═══════════════════════════════════════════════════════════
# 4. 增量插入（MD5 哈希去重，参考 nano-graphrag/_utils.py）
# ═══════════════════════════════════════════════════════════

def compute_mdhash_id(content: str, prefix: str = "") -> str:
    """
    计算内容的 MD5 哈希作为唯一 ID

    用于增量插入时去重

    参考：nano-graphrag/_utils.py:compute_mdhash_id
    """
    content_hash = hashlib.md5(content.encode()).hexdigest()
    return f"{prefix}{content_hash}"


class IncrementalDocumentStore:
    """
    增量文档存储器

    功能：
    - 使用 MD5 哈希去重
    - 避免重复处理相同内容

    参考：nano-graphrag 的增量插入逻辑
    """

    def __init__(self, working_dir: str):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self._hash_file = self.working_dir / "document_hashes.json"
        self._hashes: Dict[str, bool] = self._load_hashes()

    def _load_hashes(self) -> Dict[str, bool]:
        """加载已有文档哈希"""
        if self._hash_file.exists():
            try:
                with open(self._hash_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    async def save_hashes(self):
        """保存哈希记录"""
        with open(self._hash_file, "w") as f:
            json.dump(self._hashes, f, indent=2)

    def is_duplicate(self, content: str) -> bool:
        """检查内容是否已存在"""
        doc_hash = compute_mdhash_id(content)
        return doc_hash in self._hashes

    def mark_as_processed(self, content: str):
        """标记内容为已处理"""
        doc_hash = compute_mdhash_id(content)
        self._hashes[doc_hash] = True

    def get_new_chunks(self, chunks: List[str]) -> List[Tuple[int, str]]:
        """
        过滤出未处理的 chunks

        返回：[(chunk_index, chunk_content), ...]
        """
        new_chunks = []
        for i, chunk in enumerate(chunks):
            if not self.is_duplicate(chunk):
                new_chunks.append((i, chunk))
        return new_chunks


# ═══════════════════════════════════════════════════════════
# 5. 并发处理管道（参考 nano-graphrag/_op.py）
# ═══════════════════════════════════════════════════════════

async def process_chunks_with_limit(
    chunks: List[Tuple[int, str]],
    process_func: Callable,
    max_concurrent: int = 16,
) -> List[Any]:
    """
    并发处理 chunks（带限流）

    参考：nano-graphrag 的并发处理模式

    Args:
        chunks: [(chunk_index, chunk_content), ...]
        process_func: 异步处理函数
        max_concurrent: 最大并发数

    Returns:
        List[Any]: 处理结果列表
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(chunk):
        async with semaphore:
            idx, content = chunk
            try:
                result = await process_func(content)
                return (idx, result, None)
            except Exception as e:
                return (idx, None, str(e))

    # 并发启动所有任务
    tasks = [process_with_semaphore(chunk) for chunk in chunks]
    results = await asyncio.gather(*tasks)

    # 统计
    success_count = sum(1 for r in results if r[1] is not None)
    logger.info(f"✅ 并发处理完成: {success_count}/{len(chunks)} 成功")

    return results


# ═══════════════════════════════════════════════════════════
# 使用示例
# ═══════════════════════════════════════════════════════════

async def example_usage():
    """使用示例"""

    # 1. 初始化图存储
    graph_storage = NetworkXGraphStorage("./cache/knowledge_graph")

    # 2. 初始化文档存储（增量去重）
    doc_store = IncrementalDocumentStore("./cache/documents")

    # 3. 定义处理函数（带限流）
    @limit_async_func_call(8)
    async def process_chunk(content: str) -> Dict:
        # 这里调用 LLM 进行处理
        return {"content": content, "processed": True}

    # 4. 模拟 chunks
    chunks = [
        (0, "这是第一段内容"),
        (1, "这是第二段内容"),
        (2, "这是第三段内容"),
    ]

    # 5. 过滤已处理的 chunks
    new_chunks = doc_store.get_new_chunks([c[1] for c in chunks])
    new_chunks = [(chunks[i][0], content) for i, content in new_chunks]

    logger.info(f"📝 新 chunks: {len(new_chunks)}/{len(chunks)}")

    # 6. 并发处理
    results = await process_chunks_with_limit(
        new_chunks,
        process_chunk,
        max_concurrent=4,
    )

    # 7. 标记为已处理
    for idx, content, _ in results:
        if content:
            doc_store.mark_as_processed(content.get("content", ""))

    # 8. 保存状态
    await doc_store.save_hashes()
    await graph_storage.save_graph()


if __name__ == "__main__":
    asyncio.run(example_usage())
