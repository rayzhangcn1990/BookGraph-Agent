
"""
混合搜索管道 (llm_wiki 改进)

支持:
- 词元搜索 (tokenized search)  + 中文 CJK 大分词
- 图扩展 (2跳, 相关性排序)
- 可选向量搜索 (LanceDB)

用于在知识库中查询信息，并基于相关性返回最相关的 wiki 页面内容。
"""

import re
import math
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import defaultdict, Counter
import json

# 尝试导入向量数据库组件 (可选)
try:
    import lancedb
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False


class HybridSearchEngine:
    """混合检索引擎: 词元搜索 + 图扩展 + 向量搜索(可选)"""

    def __init__(
        self,
        pages: Dict[str, str],           # page_id -> content
        page_metadata: Dict[str, Dict],  # page_id -> {title, type, sources, ...}
        adjacency: Dict[str, Set[str]],  # 链接关系
        relevance_engine,                # GraphRelevanceEngine 实例
        vector_db_path: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_endpoint: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
    ):
        self.pages = pages
        self.page_metadata = page_metadata
        self.adjacency = adjacency
        self.relevance_engine = relevance_engine
        self.vector_db = None
        self.embedding_model = embedding_model

        # 预处理：分词存储
        self.token_to_pages = defaultdict(set)  # token -> set(page_id)
        self._build_token_index()

        # 可选向量搜索
        if LANCEDB_AVAILABLE and vector_db_path and embedding_endpoint and embedding_api_key:
            try:
                import lancedb
                import numpy as np
                import openai
                self.vector_db = lancedb.connect(vector_db_path)
                self.embedding_client = openai.OpenAI(
                    api_key=embedding_api_key,
                    base_url=embedding_endpoint
                )
                self._init_vector_table()
                print(f"✅ 向量检索已启用: {vector_db_path}")
            except Exception as e:
                print(f"⚠️ 向量检索初始化失败: {e}")

    # ---------- 词元索引 ----------
    def _tokenize_cjk(self, text: str) -> List[str]:
        """
        中英文混合分词:
        - 英文: 按空格和标点拆分，过滤停用词
        - 中文: CJK 大分词 (相邻两字滑动窗口)
        """
        tokens = set()

        # 英文/数字部分
        english_matches = re.findall(r'[a-zA-Z0-9]{2,}', text)
        for word in english_matches:
            word_low = word.lower()
            if word_low not in {'the', 'and', 'of', 'to', 'in', 'for', 'on', 'with', 'by', 'a', 'an'}:
                tokens.add(word_low)

        # 中文部分: 滑动窗口长度为2
        chinese_matches = re.findall(r'[一-鿿]+', text)
        for chinese in chinese_matches:
            if len(chinese) >= 2:
                for i in range(len(chinese) - 1):
                    tokens.add(chinese[i:i+2])
            # 单个汉字也加入
            for ch in chinese:
                tokens.add(ch)

        return list(tokens)

    def _build_token_index(self):
        """为所有页面构建 token -> page_id 倒排索引"""
        for page_id, content in self.pages.items():
            tokens = self._tokenize_cjk(content)
            # 标题加权: 重复加入标题中的 token，提高权重
            title = self.page_metadata.get(page_id, {}).get('title', '')
            title_tokens = self._tokenize_cjk(title)
            tokens.extend(title_tokens)  # 标题词出现两次 => 更高权重 (后续使用频率计分)
            for token in tokens:
                self.token_to_pages[token].add(page_id)

    def token_search(self, query: str, top_k: int = 20) -> List[Tuple[str, float]]:
        """
        词元搜索: 计算每个页面的 BM25 风格得分 (简化版: token 频率 + 标题加权)
        """
        query_tokens = self._tokenize_cjk(query)
        if not query_tokens:
            return []

        # 统计每个 token 在查询中的出现次数
        query_token_counts = Counter(query_tokens)

        # 计算逆文档频率 (IDF)
        N = len(self.pages)
        idf = {}
        for token in query_tokens:
            df = len(self.token_to_pages.get(token, set()))
            idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1) if df > 0 else 0

        # 累加每个页面的得分
        scores = defaultdict(float)
        for token, qcnt in query_token_counts.items():
            token_tf_idf = qcnt * idf.get(token, 0)
            for page_id in self.token_to_pages.get(token, set()):
                # 简化: 直接累加 TF-IDF，不单独计算文档内词频
                scores[page_id] += token_tf_idf

        # 标题加权 (出现在标题中的页面额外加分)
        for page_id, meta in self.page_metadata.items():
            title = meta.get('title', '')
            if any(t in title for t in query_tokens):
                scores[page_id] += 2.0

        # 排序
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scores[:top_k]

    # ---------- 图扩展 ----------
    def graph_expansion(self, seed_pages: List[str], max_hops: int = 2, top_k: int = 20) -> List[Tuple[str, float]]:
        """
        图扩展: 基于相关性模型找到与种子节点最相关的页面
        """
        # 直接使用 relevance_engine 的 get_top_relevant
        if self.relevance_engine:
            return self.relevance_engine.get_top_relevant(seed_pages, top_k=top_k, max_hops=max_hops)
        else:
            # 后备: 简单的 BFS
            visited = set(seed_pages)
            frontier = set(seed_pages)
            scores = defaultdict(float)
            for hop in range(max_hops):
                next_frontier = set()
                for node in frontier:
                    for neighbor in self.adjacency.get(node, set()):
                        if neighbor not in visited:
                            # 得分随跳数递减
                            scores[neighbor] += 1.0 / (hop + 1)
                            next_frontier.add(neighbor)
                visited.update(next_frontier)
                frontier = next_frontier
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return sorted_scores[:top_k]

    # ---------- 向量搜索 (可选) ----------
    def _init_vector_table(self):
        """初始化 LanceDB 表 (如果不存在)"""
        if self.vector_db is None:
            return
        # 检查表是否存在，不存在则创建
        if "wiki_embeddings" not in self.vector_db.table_names():
            # 创建空表 (需要定义 schema)
            self.vector_db.create_table("wiki_embeddings", schema={
                "vector": lancedb.vector(1536),  # OpenAI 默认维度
                "page_id": str,
                "content": str
            })

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的向量表示"""
        if self.embedding_client is None:
            return None
        try:
            response = self.embedding_client.embeddings.create(
                model=self.embedding_model or "text-embedding-ada-002",
                input=[text[:8192]]  # 截断
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"向量嵌入失败: {e}")
            return None

    def vector_search(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """基于向量的相似性搜索"""
        if self.vector_db is None:
            return []

        # 获取查询的向量
        q_emb = self.get_embedding(query)
        if q_emb is None:
            return []

        table = self.vector_db.open_table("wiki_embeddings")
        # 执行近似最近邻搜索
        results = table.search(q_emb).limit(top_k).to_pandas()
        if results is not None and not results.empty:
            return [(row['page_id'], row['_distance']) for _, row in results.iterrows()]
        return []

    def add_page_to_vector_index(self, page_id: str, content: str):
        """将新页面添加到向量索引中"""
        if self.vector_db is None:
            return
        emb = self.get_embedding(content)
        if emb:
            table = self.vector_db.open_table("wiki_embeddings")
            table.add([{"vector": emb, "page_id": page_id, "content": content[:2000]}])

    # ---------- 整体检索管道 ----------
    def search(
        self,
        query: str,
        top_k: int = 10,
        use_vector: bool = False,
        graph_expansion_hops: int = 2
    ) -> List[Tuple[str, float]]:
        """
        混合检索主接口:
        1. 词元搜索得到初始候选
        2. 可选向量搜索，合并结果
        3. 图扩展 (基于候选页面作为种子)
        """
        # 阶段1: 词元搜索
        token_results = self.token_search(query, top_k=20)
        if not token_results:
            token_results = []

        # 阶段2: 向量搜索 (如果启用)
        vector_results = []
        if use_vector and self.vector_db:
            vector_results = self.vector_search(query, top_k=10)

        # 合并: 词元得分 + 向量得分 (简单加权)
        combined_scores = defaultdict(float)
        for pid, score in token_results:
            combined_scores[pid] += score
        for pid, score in vector_results:
            combined_scores[pid] += score * 2.0  # 向量得分权重可调

        # 取 top 候选作为种子
        seed_pages = [pid for pid, _ in sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)[:5]]

        # 阶段3: 图扩展
        graph_results = []
        if graph_expansion_hops > 0 and seed_pages:
            graph_results = self.graph_expansion(seed_pages, max_hops=graph_expansion_hops, top_k=top_k)

        # 最终融合: 词元得分 + 图扩展得分
        final_scores = defaultdict(float)
        for pid, score in token_results:
            final_scores[pid] += score
        for pid, score in graph_results:
            final_scores[pid] += score * 1.5  # 图相关性权重

        # 排序并返回
        sorted_final = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_final[:top_k]

    def get_page_content(self, page_id: str) -> Optional[str]:
        """获取页面内容"""
        return self.pages.get(page_id)

    def format_search_results(self, results: List[Tuple[str, float]]) -> str:
        """将搜索结果格式化为可读的字符串"""
        lines = []
        lines.append("## 搜索结果")
        lines.append("")
        for i, (pid, score) in enumerate(results[:10], 1):
            meta = self.page_metadata.get(pid, {})
            title = meta.get('title', pid)
            lines.append(f"{i}. **{title}** (相关性: {score:.2f})")
            # 可以添加简短摘要
            content = self.pages.get(pid, '')[:200]
            if content:
                lines.append(f"   {content}")
            lines.append("")
        return "\n".join(lines)
