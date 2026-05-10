
"""
4‑信号知识图相关性模型 (4‑signal knowledge graph relevance model)

权重配置 (基于 llm_wiki):
- 直接链接 ×3.0  (pages linked via [[wikilinks]])
- 来源重叠 ×4.0  (pages sharing same raw source via frontmatter sources[])
- Adamic‑Adar ×1.5  (pages sharing common neighbors, weighted by neighbor degree)
- 类型亲和 ×1.0  (same page type: entity↔entity, concept↔concept)

适用于: 计算任意两个节点之间的相关性得分，用于图扩展、查询召回等。
"""

import math
from collections import defaultdict, Counter
from typing import Dict, List, Set, Optional, Tuple, Any
import json


class GraphRelevanceEngine:
    """图相关性引擎 - 4‑信号模型"""

    # 默认权重
    WEIGHT_DIRECT_LINK = 3.0
    WEIGHT_SOURCE_OVERLAP = 4.0
    WEIGHT_ADAMIC_ADAR = 1.5
    WEIGHT_TYPE_AFFINITY = 1.0

    def __init__(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Tuple[str, str]],
        node_type_map: Dict[str, str],
        source_to_nodes: Dict[str, Set[str]],
    ):
        """
        初始化相关性引擎

        Args:
            nodes: 节点列表，每个节点至少包含 id, type
            edges: 边列表，每个元素为 (source_id, target_id)
            node_type_map: node_id -> type (entity/concept/source等)
            source_to_nodes: 原始来源ID -> 该来源包含的节点ID集合
        """
        self.nodes = {n['id']: n for n in nodes} if isinstance(nodes, list) else nodes
        self.node_type_map = node_type_map
        self.source_to_nodes = source_to_nodes

        # 构建邻接表
        self.adjacency = defaultdict(set)
        self.degree = defaultdict(int)
        for u, v in edges:
            self.adjacency[u].add(v)
            self.adjacency[v].add(u)
        for node, neighbors in self.adjacency.items():
            self.degree[node] = len(neighbors)

        # 构建节点到来源的倒排索引
        self.node_to_sources = defaultdict(set)
        for source, node_set in source_to_nodes.items():
            for node in node_set:
                self.node_to_sources[node].add(source)

        # 缓存常见计算结果
        self._aa_cache = {}

    @classmethod
    def from_book_graph(cls, book_graph, sources_field: str = "sources"):
        """
        从 BookGraph 对象构建引擎

        Args:
            book_graph: BookGraph 实例 (或包含 chapters/core_concepts等)
            sources_field: 节点中表示来源的字段名 (如 frontmatter 中的 sources)
        """
        nodes = []
        node_type_map = {}
        source_to_nodes = defaultdict(set)

        # 处理 metadata
        if hasattr(book_graph, 'metadata') and book_graph.metadata:
            nodes.append({'id': f"metadata:{book_graph.metadata.title}", 'type': 'metadata'})
            node_type_map[f"metadata:{book_graph.metadata.title}"] = 'metadata'

        # 处理 chapters
        if hasattr(book_graph, 'chapters') and book_graph.chapters:
            for ch in book_graph.chapters:
                node_id = f"chapter:{ch.chapter_number}"
                nodes.append({'id': node_id, 'type': 'chapter'})
                node_type_map[node_id] = 'chapter'
                # 如果有 sources 字段，添加到映射
                if hasattr(ch, sources_field) and getattr(ch, sources_field):
                    for src in getattr(ch, sources_field):
                        source_to_nodes[src].add(node_id)

        # 处理 core_concepts
        if hasattr(book_graph, 'core_concepts') and book_graph.core_concepts:
            for concept in book_graph.core_concepts:
                node_id = f"concept:{concept.name}"
                nodes.append({'id': node_id, 'type': 'concept'})
                node_type_map[node_id] = 'concept'
                if hasattr(concept, sources_field) and getattr(concept, sources_field):
                    for src in getattr(concept, sources_field):
                        source_to_nodes[src].add(node_id)

        # 处理 key_insights
        if hasattr(book_graph, 'key_insights') and book_graph.key_insights:
            for ins in book_graph.key_insights:
                node_id = f"insight:{ins.title}"
                nodes.append({'id': node_id, 'type': 'insight'})
                node_type_map[node_id] = 'insight'
                if hasattr(ins, sources_field) and getattr(ins, sources_field):
                    for src in getattr(ins, sources_field):
                        source_to_nodes[src].add(node_id)

        # 构建边: 基于硬编码的引用关系 (例如 chapter 引用 concept)
        edges = []
        for ch in getattr(book_graph, 'chapters', []):
            ch_id = f"chapter:{ch.chapter_number}"
            # 从 core_argument / underlying_logic 中提取概念名 (简易: 精确匹配 vs 可以后续完善)
            # 这里先留空，允许外部传入边列表
            pass

        return cls(nodes, edges, node_type_map, dict(source_to_nodes))

    def direct_link_signal(self, u: str, v: str) -> float:
        """信号1: 直接链接 (有边则返回权重，无边返回0)"""
        return self.WEIGHT_DIRECT_LINK if v in self.adjacency[u] else 0.0

    def source_overlap_signal(self, u: str, v: str) -> float:
        """信号2: 来源重叠 (Jaccard 相似度 * 权重)"""
        sources_u = self.node_to_sources.get(u, set())
        sources_v = self.node_to_sources.get(v, set())
        if not sources_u or not sources_v:
            return 0.0
        intersection = len(sources_u & sources_v)
        union = len(sources_u | sources_v)
        if union == 0:
            return 0.0
        jaccard = intersection / union
        return jaccard * self.WEIGHT_SOURCE_OVERLAP

    def adamic_adar_signal(self, u: str, v: str) -> float:
        """信号3: Adamic‑Adar 指数 (基于共同邻居的度对数倒数之和)"""
        if u == v:
            return 0.0
        # 缓存检查
        key = tuple(sorted((u, v)))
        if key in self._aa_cache:
            return self._aa_cache[key]

        neighbors_u = self.adjacency.get(u, set())
        neighbors_v = self.adjacency.get(v, set())
        common = neighbors_u & neighbors_v

        score = 0.0
        for w in common:
            deg_w = self.degree.get(w, 1)
            if deg_w > 1:
                score += 1.0 / math.log(deg_w)
        score *= self.WEIGHT_ADAMIC_ADAR
        self._aa_cache[key] = score
        return score

    def type_affinity_signal(self, u: str, v: str) -> float:
        """信号4: 类型亲和 (同类型则返回权重，否则0)"""
        type_u = self.node_type_map.get(u, 'unknown')
        type_v = self.node_type_map.get(v, 'unknown')
        if type_u == type_v and type_u != 'unknown':
            return self.WEIGHT_TYPE_AFFINITY
        return 0.0

    def total_relevance(self, u: str, v: str) -> float:
        """
        计算两个节点的总相关性得分 (4‑信号加权和)
        """
        return (
            self.direct_link_signal(u, v) +
            self.source_overlap_signal(u, v) +
            self.adamic_adar_signal(u, v) +
            self.type_affinity_signal(u, v)
        )

    def get_top_relevant(self, seed_nodes: List[str], top_k: int = 10, max_hops: int = 2) -> List[Tuple[str, float]]:
        """
        给定种子节点集合，返回与之最相关的其他节点 (按总相关性排序)

        Args:
            seed_nodes: 初始节点列表
            top_k: 返回数量
            max_hops: 图扩展的最大跳数 (0 = 仅种子自身)

        Returns:
            List[(node_id, score)] 按得分降序排列
        """
        candidate_scores = defaultdict(float)
        visited = set(seed_nodes)

        # BFS 扩展
        current_frontier = set(seed_nodes)
        for hop in range(max_hops):
            next_frontier = set()
            for node in current_frontier:
                for neighbor in self.adjacency.get(node, set()):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
            # 为这一跳发现的节点计算与所有种子节点的相关性 (取最大值)
            for cand in next_frontier:
                max_score = 0.0
                for seed in seed_nodes:
                    score = self.total_relevance(seed, cand)
                    if score > max_score:
                        max_score = score
                if max_score > 0:
                    candidate_scores[cand] = max(candidate_scores[cand], max_score)
            visited.update(next_frontier)
            current_frontier = next_frontier

        # 排序并返回 top_k
        sorted_candidates = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_candidates[:top_k]

    def compute_relevance_matrix(self, node_ids: List[str]) -> Dict[Tuple[str, str], float]:
        """计算节点列表之间的两两相关性矩阵 (用于调试/可视化)"""
        matrix = {}
        n = len(node_ids)
        for i in range(n):
            for j in range(i + 1, n):
                u, v = node_ids[i], node_ids[j]
                score = self.total_relevance(u, v)
                if score > 0:
                    matrix[(u, v)] = score
        return matrix
