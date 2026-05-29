"""
实体消歧与对齐
使用轻量级 sentence-transformers 模型对核心概念进行聚类合并。
"""

import logging
from typing import List, Dict, Any, Set
from collections import defaultdict

logger = logging.getLogger("BookGraph-Agent")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("⚠️ sentence-transformers 未安装，实体消歧功能不可用")


class EntityResolver:
    """实体解析器：基于向量相似度合并相似概念"""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", similarity_threshold: float = 0.85):
        self.model = None
        self.similarity_threshold = similarity_threshold
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer(model_name)
                logger.info(f"✅ 实体消歧模型加载成功: {model_name}")
            except Exception as e:
                logger.error(f"❌ 加载实体消歧模型失败: {e}")

    def resolve_concepts(self, concepts: List[Dict]) -> List[Dict]:
        """
        合并相似的概念。

        Args:
            concepts: 概念列表，每个概念包含 name, definition, ... 等字段

        Returns:
            合并后的概念列表
        """
        if not self.model or len(concepts) <= 1:
            return concepts

        # 提取概念名称和定义用于向量化
        texts = []
        for c in concepts:
            name = c.get('name', '')
            definition = c.get('definition', '')
            text = f"{name}: {definition}" if definition else name
            texts.append(text)

        # 计算 embeddings
        embeddings = self.model.encode(texts, normalize_embeddings=True)

        # 贪心聚类：若余弦相似度 > threshold 则合并
        n = len(concepts)
        merged_flags = [False] * n
        merged_concepts = []

        for i in range(n):
            if merged_flags[i]:
                continue
            cluster = [i]
            for j in range(i+1, n):
                if merged_flags[j]:
                    continue
                sim = float(embeddings[i] @ embeddings[j])
                if sim >= self.similarity_threshold:
                    cluster.append(j)
                    merged_flags[j] = True
            # 合并 cluster 中的概念
            if len(cluster) == 1:
                merged_concepts.append(concepts[i])
            else:
                # 取第一个作为基础，合并名称和定义
                base = concepts[cluster[0]].copy()
                base['name'] = base['name']  # 保留第一个名称
                # 合并定义：用分号连接
                definitions = [concepts[idx].get('definition', '') for idx in cluster if concepts[idx].get('definition')]
                if definitions:
                    base['definition'] = '; '.join(definitions)
                # 合并来源（如果存在）
                sources = set()
                for idx in cluster:
                    src = concepts[idx].get('sources', [])
                    if isinstance(src, list):
                        sources.update(src)
                if sources:
                    base['sources'] = list(sources)
                # 可选：合并深层含义等
                merged_concepts.append(base)
                logger.info(f"🔗 合并相似概念: {base['name']} (来自 {len(cluster)} 个原始概念)")

        return merged_concepts
