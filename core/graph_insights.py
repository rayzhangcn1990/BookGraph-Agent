
"""
图洞察模块 (Graph Insights) - 基于 llm_wiki

功能:
1. Louvain 社区检测 - 自动发现知识聚类
2. 孤立节点检测 (degree <= 1)
3. 桥节点检测 (连接 >= 3 个社区)
4. 稀疏社区检测 (cohesion < 0.15)
5. 生成洞察报告
"""

import math
from collections import defaultdict, Counter
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Community:
    """社区数据结构"""
    id: int
    nodes: List[str]
    cohesion: float  # 内部边密度 = 实际边数 / 可能的最大边数
    top_labels: List[str]  # 最重要的节点标签


@dataclass
class GraphInsight:
    """图洞察"""
    type: str  # "isolated", "bridge", "sparse_community"
    nodes: List[str]
    description: str
    score: float  # 重要性分数 (0-1)
    deep_research_topic: Optional[str] = None


class GraphInsightsEngine:
    """图洞察引擎 - 基于 Louvain 社区检测"""

    def __init__(self, adjacency: Dict[str, Set[str]], node_labels: Dict[str, str]):
        """
        初始化

        Args:
            adjacency: 邻接表 {node_id: set(neighbors)}
            node_labels: 节点标签 {node_id: label}
        """
        self.adjacency = adjacency
        self.node_labels = node_labels
        self.nodes = list(adjacency.keys())
        self.n = len(self.nodes)
        self.node_to_idx = {node: i for i, node in enumerate(self.nodes)}
        self.idx_to_node = {i: node for i, node in enumerate(self.nodes)}

        # 构建边列表 (用于 Louvain)
        self.edges = []
        for u, neighbors in adjacency.items():
            for v in neighbors:
                if u < v:  # 无向图，每条边只加一次
                    self.edges.append((self.node_to_idx[u], self.node_to_idx[v]))

        # 缓存社区检测结果
        self._communities = None
        self._modularity = None

    def detect_communities_louvain(self) -> List[Community]:
        """
        使用 Louvain 算法检测社区

        Returns:
            List[Community]: 社区列表
        """
        try:
            # 尝试导入 graphology 的 Louvain 实现 (Python 版本)
            # 如果没有，使用简化的贪心聚类
            from community import community_louvain
            import networkx as nx

            # 构建 NetworkX 图
            G = nx.Graph()
            for u, neighbors in self.adjacency.items():
                for v in neighbors:
                    G.add_edge(u, v)

            # Louvain 社区检测
            partition = community_louvain.best_partition(G)

            # 按社区分组
            communities_dict = defaultdict(list)
            for node, comm_id in partition.items():
                communities_dict[comm_id].append(node)

            # 计算每个社区的凝聚力和 top 标签
            communities = []
            for comm_id, nodes in communities_dict.items():
                # 计算凝聚力 (内部边密度)
                internal_edges = 0
                possible_edges = len(nodes) * (len(nodes) - 1) / 2
                for u in nodes:
                    for v in self.adjacency.get(u, set()):
                        if v in nodes and u < v:
                            internal_edges += 1
                cohesion = internal_edges / possible_edges if possible_edges > 0 else 0.0

                # 获取 top 标签 (按度排序)
                node_degrees = [(node, len(self.adjacency.get(node, set()))) for node in nodes]
                node_degrees.sort(key=lambda x: x[1], reverse=True)
                top_labels = [self.node_labels.get(node, node) for node, _ in node_degrees[:3]]

                communities.append(Community(
                    id=comm_id,
                    nodes=nodes,
                    cohesion=cohesion,
                    top_labels=top_labels
                ))

            self._communities = communities
            return communities

        except ImportError:
            # 后备方案: 简化的贪心聚类 (基于连接强度)
            return self._greedy_clustering()

    def _greedy_clustering(self) -> List[Community]:
        """简化的贪心聚类 (当 networkx/community 不可用时)"""
        # 使用度中心性简单分组
        nodes_by_degree = sorted(self.nodes, key=lambda n: len(self.adjacency.get(n, set())), reverse=True)

        communities = []
        visited = set()

        for seed in nodes_by_degree:
            if seed in visited:
                continue
            # 贪心扩展: 包括种子及其直接邻居
            community_nodes = {seed}
            community_nodes.update(self.adjacency.get(seed, set()))
            community_nodes = list(community_nodes)
            visited.update(community_nodes)

            # 计算凝聚力
            internal_edges = 0
            possible_edges = len(community_nodes) * (len(community_nodes) - 1) / 2
            for u in community_nodes:
                for v in self.adjacency.get(u, set()):
                    if v in community_nodes and u < v:
                        internal_edges += 1
            cohesion = internal_edges / possible_edges if possible_edges > 0 else 0.0

            top_labels = [self.node_labels.get(n, n) for n in community_nodes[:3]]
            communities.append(Community(
                id=len(communities),
                nodes=community_nodes,
                cohesion=cohesion,
                top_labels=top_labels
            ))

        self._communities = communities
        return communities

    def find_isolated_nodes(self, degree_threshold: int = 1) -> List[GraphInsight]:
        """
        查找孤立节点 (degree <= threshold)

        Returns:
            List[GraphInsight]: 孤立节点洞察列表
        """
        insights = []
        for node in self.nodes:
            degree = len(self.adjacency.get(node, set()))
            if degree <= degree_threshold:
                label = self.node_labels.get(node, node)
                insights.append(GraphInsight(
                    type="isolated",
                    nodes=[node],
                    description=f"孤立节点: {label} (度: {degree})",
                    score=1.0 - (degree / max(degree_threshold + 1, 1))
                ))
        return insights

    def find_bridge_nodes(self, min_communities: int = 3) -> List[GraphInsight]:
        """
        查找桥节点 (连接至少 min_communities 个社区)

        Returns:
            List[GraphInsight]: 桥节点洞察列表
        """
        if self._communities is None:
            self.detect_communities_louvain()

        # 构建 node -> community_id 映射
        node_to_comm = {}
        for comm in self._communities:
            for node in comm.nodes:
                node_to_comm[node] = comm.id

        insights = []
        for node in self.nodes:
            # 获取该节点邻居所属的社区集合
            neighbor_comms = set()
            for neighbor in self.adjacency.get(node, set()):
                if neighbor in node_to_comm:
                    neighbor_comms.add(node_to_comm[neighbor])

            if len(neighbor_comms) >= min_communities:
                label = self.node_labels.get(node, node)
                insights.append(GraphInsight(
                    type="bridge",
                    nodes=[node],
                    description=f"桥节点: {label} 连接 {len(neighbor_comms)} 个社区",
                    score=min(1.0, len(neighbor_comms) / (min_communities + 2))
                ))
        return insights

    def find_sparse_communities(self, cohesion_threshold: float = 0.15) -> List[GraphInsight]:
        """
        查找稀疏社区 (凝聚力 < threshold)

        Returns:
            List[GraphInsight]: 稀疏社区洞察列表
        """
        if self._communities is None:
            self.detect_communities_louvain()

        insights = []
        for comm in self._communities:
            if comm.cohesion < cohesion_threshold and len(comm.nodes) >= 3:
                insights.append(GraphInsight(
                    type="sparse_community",
                    nodes=comm.nodes,
                    description=f"稀疏社区 (凝聚力: {comm.cohesion:.3f}): {', '.join(comm.top_labels)}",
                    score=1.0 - (comm.cohesion / cohesion_threshold)
                ))
        return insights

    def generate_insights_report(
        self,
        degree_threshold: int = 1,
        bridge_min_communities: int = 3,
        cohesion_threshold: float = 0.15
    ) -> Dict[str, List[GraphInsight]]:
        """
        生成完整的图洞察报告

        Returns:
            Dict: {
                "isolated": [...],
                "bridge": [...],
                "sparse_communities": [...]
            }
        """
        # 检测社区 (如果没有)
        if self._communities is None:
            self.detect_communities_louvain()

        return {
            "isolated": self.find_isolated_nodes(degree_threshold),
            "bridge": self.find_bridge_nodes(bridge_min_communities),
            "sparse_communities": self.find_sparse_communities(cohesion_threshold)
        }

    def get_community_summary(self) -> Dict:
        """获取社区摘要统计"""
        if self._communities is None:
            self.detect_communities_louvain()

        community_sizes = [len(comm.nodes) for comm in self._communities]
        cohesion_scores = [comm.cohesion for comm in self._communities]

        return {
            "num_communities": len(self._communities),
            "avg_community_size": sum(community_sizes) / len(community_sizes) if community_sizes else 0,
            "avg_cohesion": sum(cohesion_scores) / len(cohesion_scores) if cohesion_scores else 0,
            "modularity": self._modularity,
            "communities": [
                {
                    "id": comm.id,
                    "size": len(comm.nodes),
                    "cohesion": comm.cohesion,
                    "top_labels": comm.top_labels
                }
                for comm in self._communities
            ]
        }


def build_insights_from_book_graph(book_graph) -> GraphInsightsEngine:
    """
    从 BookGraph 对象构建图洞察引擎

    Args:
        book_graph: BookGraph 实例

    Returns:
        GraphInsightsEngine: 图洞察引擎
    """
    adjacency = defaultdict(set)
    node_labels = {}

    # 添加章节节点
    if hasattr(book_graph, 'chapters') and book_graph.chapters:
        for ch in book_graph.chapters:
            node_id = f"chapter:{ch.chapter_number}"
            node_labels[node_id] = f"第{ch.chapter_number}章: {ch.title}"
            # 基于 core_argument 中的概念名建立连接 (简化: 使用关键词匹配)
            # 这里先不自动建立边，允许外部传入

    # 添加概念节点
    if hasattr(book_graph, 'core_concepts') and book_graph.core_concepts:
        for concept in book_graph.core_concepts:
            node_id = f"concept:{concept.name}"
            node_labels[node_id] = concept.name

    # 添加洞察节点
    if hasattr(book_graph, 'key_insights') and book_graph.key_insights:
        for insight in book_graph.key_insights:
            node_id = f"insight:{insight.title}"
            node_labels[node_id] = insight.title

    # 构建边: 基于共同出现 (如果两个节点出现在同一章节/上下文中)
    # 简化版: 留空，由调用者提供边列表

    return GraphInsightsEngine(dict(adjacency), node_labels)


def format_insights_for_report(insights: Dict[str, List[GraphInsight]]) -> str:
    """格式化洞察为 Markdown 报告"""
    lines = []
    lines.append("## 知识图谱洞察报告")
    lines.append("")

    # 孤立节点
    if insights["isolated"]:
        lines.append("### 孤立节点")
        lines.append("")
        for ins in insights["isolated"]:
            lines.append(f"- {ins.description} (重要性: {ins.score:.2f})")
        lines.append("")

    # 桥节点
    if insights["bridge"]:
        lines.append("### 桥节点")
        lines.append("")
        for ins in insights["bridge"]:
            lines.append(f"- {ins.description} (重要性: {ins.score:.2f})")
        lines.append("")

    # 稀疏社区
    if insights["sparse_communities"]:
        lines.append("### 稀疏社区")
        lines.append("")
        for ins in insights["sparse_communities"]:
            lines.append(f"- {ins.description} (得分: {ins.score:.2f})")
        lines.append("")

    if not any(insights.values()):
        lines.append("✅ 未发现明显的问题节点或社区。")

    return "\n".join(lines)
