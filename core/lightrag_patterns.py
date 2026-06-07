"""
参考 LightRAG 实现增量构建和实体消歧

关键学习点：
1. 增量插入（MD5 哈希去重）
2. 实体消歧算法
3. 知识图谱合并策略
4. 文档删除后自动重新生成图谱

参考：https://github.com/HKUDS/LightRAG
"""

import asyncio
import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("BookGraph-Agent")


# ═══════════════════════════════════════════════════════════
# 1. 增量插入与去重（参考 LightRAG/operate.py）
# ═══════════════════════════════════════════════════════════

@dataclass
class IncrementalGraphBuilder:
    """
    增量知识图谱构建器

    功能：
    - 使用 MD5 哈希去重，避免重复处理
    - 增量添加新文档，不重新处理已有内容
    - 文档删除后自动重新计算图谱

    参考：LightRAG 的增量插入逻辑
    """

    working_dir: str
    namespace: str = "book_knowledge"

    # 已处理的文档哈希
    processed_docs: Dict[str, Dict] = field(default_factory=dict)

    # 实体索引（用于消歧）
    entity_index: Dict[str, Set[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.working_path = Path(self.working_dir)
        self.working_path.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def _load_state(self):
        """加载已处理状态"""
        state_file = self.working_path / f"{self.namespace}_state.json"
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_docs = data.get("processed_docs", {})
                    self.entity_index = {k: set(v) for k, v in data.get("entity_index", {}).items()}
                logger.info(f"📂 加载状态: {len(self.processed_docs)} 文档已处理")
            except Exception as e:
                logger.warning(f"⚠️ 加载状态失败: {e}")

    async def save_state(self):
        """保存处理状态"""
        state_file = self.working_path / f"{self.namespace}_state.json"
        data = {
            "processed_docs": self.processed_docs,
            "entity_index": {k: list(v) for k, v in self.entity_index.items()},
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 保存状态: {len(self.processed_docs)} 文档")

    def compute_doc_hash(self, content: str) -> str:
        """计算文档哈希"""
        return hashlib.md5(content.encode()).hexdigest()

    def is_doc_processed(self, doc_hash: str) -> bool:
        """检查文档是否已处理"""
        return doc_hash in self.processed_docs

    def mark_doc_processed(self, doc_hash: str, doc_metadata: Dict):
        """标记文档为已处理"""
        self.processed_docs[doc_hash] = {
            "metadata": doc_metadata,
            "processed_at": asyncio.get_event_loop().time(),
        }

    def get_unprocessed_chunks(
        self,
        chunks: List[Tuple[int, str, str]],  # (index, content, label)
    ) -> List[Tuple[int, str, str]]:
        """
        过滤出未处理的 chunks

        参考：LightRAG 的增量插入逻辑
        """
        unprocessed = []
        for idx, content, label in chunks:
            chunk_hash = self.compute_doc_hash(content)
            if not self.is_doc_processed(chunk_hash):
                unprocessed.append((idx, content, label))
        return unprocessed

    async def add_document(
        self,
        doc_content: str,
        doc_metadata: Dict,
        process_func: callable,
    ) -> Dict:
        """
        增量添加文档

        Args:
            doc_content: 文档内容
            doc_metadata: 文档元数据
            process_func: 处理函数（异步）

        Returns:
            Dict: 处理结果
        """
        doc_hash = self.compute_doc_hash(doc_content)

        # 检查是否已处理
        if self.is_doc_processed(doc_hash):
            logger.info(f"⏭️ 文档已处理，跳过: {doc_metadata.get('title', 'Unknown')}")
            return {"status": "skipped", "reason": "already_processed"}

        # 处理文档
        logger.info(f"📝 处理新文档: {doc_metadata.get('title', 'Unknown')}")
        result = await process_func(doc_content, doc_metadata)

        # 标记为已处理
        self.mark_doc_processed(doc_hash, doc_metadata)

        # 保存状态
        await self.save_state()

        return {"status": "processed", "result": result}

    async def remove_document(self, doc_hash: str):
        """
        删除文档并更新图谱

        参考：LightRAG 的文档删除逻辑
        """
        if doc_hash in self.processed_docs:
            del self.processed_docs[doc_hash]
            logger.info(f"🗑️ 删除文档: {doc_hash}")

            # 清理实体索引中与该文档相关的条目
            for entity_name, doc_hashes in list(self.entity_index.items()):
                if doc_hash in doc_hashes:
                    doc_hashes.remove(doc_hash)
                if not doc_hashes:
                    del self.entity_index[entity_name]

            await self.save_state()


# ═══════════════════════════════════════════════════════════
# 2. 实体消歧算法（参考 LightRAG）
# ═══════════════════════════════════════════════════════════

@dataclass
class EntityDisambiguation:
    """
    实体消歧处理器

    功能：
    - 合并相似实体（同一概念不同表述）
    - 实体链接（将提及链接到规范实体）
    - 实体聚类（按语义相似度聚类）

    参考：LightRAG 的实体合并逻辑
    """

    # 实体规范化映射（别名 -> 规范名）
    entity_canonical_map: Dict[str, str] = field(default_factory=dict)

    # 实体描述合并（规范名 -> 描述列表）
    entity_descriptions: Dict[str, List[str]] = field(default_factory=dict)

    def normalize_entity_name(self, name: str) -> str:
        """
        规范化实体名称

        规则：
        - 统一大小写
        - 去除多余空格
        - 应用已知的别名映射
        """
        # 基础规范化
        normalized = name.strip().upper()

        # 应用已知映射
        if normalized in self.entity_canonical_map:
            return self.entity_canonical_map[normalized]

        return normalized

    def should_merge_entities(
        self,
        entity1: Dict,
        entity2: Dict,
        similarity_threshold: float = 0.85,
    ) -> bool:
        """
        判断两个实体是否应该合并

        参考：LightRAG 的实体合并策略

        规则：
        - 名称完全匹配
        - 名称相似度超过阈值
        - 描述语义相似度超过阈值
        """
        name1 = self.normalize_entity_name(entity1.get("name", ""))
        name2 = self.normalize_entity_name(entity2.get("name", ""))

        # 名称完全匹配
        if name1 == name2:
            return True

        # 名称相似度（简化版，实际应使用向量相似度）
        name_similarity = self._compute_string_similarity(name1, name2)
        if name_similarity >= similarity_threshold:
            return True

        return False

    def _compute_string_similarity(self, str1: str, str2: str) -> float:
        """
        计算字符串相似度（Jaccard）

        实际应使用 embedding 向量相似度
        """
        set1 = set(str1)
        set2 = set(str2)

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def merge_entities(
        self,
        entities: List[Dict],
    ) -> List[Dict]:
        """
        合并相似实体

        参考：LightRAG 的实体合并逻辑

        策略：
        1. 按名称规范化分组
        2. 同组实体合并描述
        3. 保留最强关联
        """
        # 按规范化名称分组
        entity_groups: Dict[str, List[Dict]] = defaultdict(list)

        for entity in entities:
            normalized_name = self.normalize_entity_name(entity.get("name", ""))
            entity_groups[normalized_name].append(entity)

        # 合并每组
        merged_entities = []
        for canonical_name, group in entity_groups.items():
            if len(group) == 1:
                merged_entities.append(group[0])
            else:
                # 合并描述
                merged_entity = {
                    "name": canonical_name,
                    "description": "\n".join([
                        e.get("description", "")
                        for e in group
                        if e.get("description")
                    ]),
                    "source_count": len(group),
                    "merged_from": [e.get("name", "") for e in group],
                }

                # 合并类型（取最常见）
                types = [e.get("type", "未知") for e in group]
                merged_entity["type"] = max(set(types), key=types.count)

                merged_entities.append(merged_entity)

                # 更新映射
                for e in group:
                    self.entity_canonical_map[self.normalize_entity_name(e.get("name", ""))] = canonical_name

        logger.info(f"🔗 实体合并: {len(entities)} → {len(merged_entities)}")
        return merged_entities

    def link_entity_mentions(
        self,
        text: str,
        known_entities: Dict[str, Dict],
    ) -> List[Tuple[str, str, int, int]]:
        """
        实体链接：在文本中识别并链接已知实体

        参考：LightRAG 的实体链接逻辑

        Args:
            text: 待处理的文本
            known_entities: 已知实体字典 {规范化名称: 实体信息}

        Returns:
            List[Tuple[str, str, int, int]]: [(原文提及, 规范名称, 起始位置, 结束位置), ...]
        """
        mentions = []

        for canonical_name in known_entities:
            # 尝试匹配规范化名称
            pattern = re.compile(re.escape(canonical_name), re.IGNORECASE)

            for match in pattern.finditer(text):
                mentions.append((
                    match.group(),  # 原文提及
                    canonical_name,  # 规范名称
                    match.start(),   # 起始位置
                    match.end(),     # 结束位置
                ))

        return mentions


# ═══════════════════════════════════════════════════════════
# 3. 知识图谱合并策略（参考 LightRAG）
# ═══════════════════════════════════════════════════════════

class KnowledgeGraphMerger:
    """
    知识图谱合并器

    功能：
    - 合并多本书籍的图谱到学科图谱
    - 避免重复节点和边
    - 更新关联关系

    参考：LightRAG 的图谱更新逻辑
    """

    def __init__(self):
        self.disambiguation = EntityDisambiguation()

    def merge_graphs(
        self,
        target_graph: Dict,
        source_graph: Dict,
        book_title: str,
    ) -> Dict:
        """
        将源图谱合并到目标图谱

        参考：LightRAG 的图谱合并策略

        Args:
            target_graph: 目标图谱（学科图谱）
            source_graph: 源图谱（书籍图谱）
            book_title: 书名（用于溯源）

        Returns:
            Dict: 合并后的图谱
        """
        # 合并核心概念
        if "core_concepts" in source_graph:
            target_concepts = target_graph.setdefault("core_concepts", [])
            source_concepts = source_graph.get("core_concepts", [])

            # 消歧后合并
            merged_concepts = self.disambiguation.merge_entities(
                target_concepts + source_concepts
            )
            target_graph["core_concepts"] = merged_concepts

        # 合并关键洞见
        if "key_insights" in source_graph:
            target_insights = target_graph.setdefault("key_insights", [])
            for insight in source_graph.get("key_insights", []):
                # 添加来源标记
                insight_with_source = {**insight, "source_book": book_title}
                target_insights.append(insight_with_source)

        # 合并金句
        if "key_quotes" in source_graph:
            target_quotes = target_graph.setdefault("key_quotes", [])
            for quote in source_graph.get("key_quotes", []):
                quote_with_source = {**quote, "source_book": book_title}
                target_quotes.append(quote_with_source)

        # 合并案例
        if "key_cases" in source_graph:
            target_cases = target_graph.setdefault("key_cases", [])
            for case in source_graph.get("key_cases", []):
                case_with_source = {**case, "source_book": book_title}
                target_cases.append(case_with_source)

        # 更新书籍网络
        book_network = target_graph.setdefault("book_network", {})
        if book_title not in book_network:
            book_network[book_title] = []

        # 添加关联书籍
        related_books = source_graph.get("metadata", {}).get("related_books", [])
        for related in related_books:
            if isinstance(related, str):
                book_network[book_title].append(related)
            elif isinstance(related, dict):
                book_network[book_title].append(related.get("title", ""))

        logger.info(f"📊 合并图谱: {book_title}")

        return target_graph


# ═══════════════════════════════════════════════════════════
# 使用示例
# ═══════════════════════════════════════════════════════════

async def example_usage():
    """使用示例"""

    # 1. 增量构建器
    builder = IncrementalGraphBuilder("./cache/incremental")

    # 模拟文档
    docs = [
        ("这是第一本书的内容...", {"title": "书A"}),
        ("这是第二本书的内容...", {"title": "书B"}),
        ("这是第一本书的内容...", {"title": "书A（重复）"}),  # 应该被跳过
    ]

    async def process_doc(content, metadata):
        return {"content_length": len(content), "title": metadata.get("title")}

    for content, metadata in docs:
        result = await builder.add_document(content, metadata, process_doc)
        print(f"结果: {result['status']}")

    # 2. 实体消歧
    disambiguation = EntityDisambiguation()

    entities = [
        {"name": "马克思", "description": "德国哲学家", "type": "人物"},
        {"name": "Karl Marx", "description": "马克思主义创始人", "type": "人物"},
        {"name": "马克思主义", "description": "政治经济学理论", "type": "概念"},
    ]

    merged = disambiguation.merge_entities(entities)
    print(f"合并后: {len(merged)} 个实体")

    # 3. 图谱合并
    merger = KnowledgeGraphMerger()

    discipline_graph = {
        "core_concepts": [{"name": "国家", "description": "政治实体"}],
        "key_insights": [],
    }

    book_graph = {
        "core_concepts": [
            {"name": "阶级", "description": "社会分层概念"},
            {"name": "国家", "description": "阶级统治工具"},
        ],
        "key_insights": [{"title": "国家是阶级统治工具"}],
        "key_quotes": [{"text": "全世界无产者，联合起来！"}],
        "metadata": {"title": "共产党宣言", "related_books": ["资本论"]},
    }

    merged_graph = merger.merge_graphs(discipline_graph, book_graph, "共产党宣言")
    print(f"合并后核心概念: {len(merged_graph['core_concepts'])}")


if __name__ == "__main__":
    asyncio.run(example_usage())
