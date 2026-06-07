
"""
两阶段 Chain-of-Thought 摄取 (llm_wiki 改进)
阶段1: 分析 -> 阶段2: 生成
支持增量缓存 + 检查点恢复
"""

import asyncio
import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from utils.parse_cache import get_cache

logger = logging.getLogger("BookGraph-Agent")


class TwoStageIngest:
    """
    两阶段摄取管理器

    支持检查点保存和恢复，确保失败时不会丢失已分析的结果
    """

    def __init__(self, checkpoint_dir: Optional[str] = None):
        """
        初始化两阶段摄取管理器

        Args:
            checkpoint_dir: 检查点保存目录，默认为 cache/checkpoints
        """
        self.cache = get_cache()
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path("cache/checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, book_title: str, stage: str, data: Dict) -> None:
        """
        保存检查点

        Args:
            book_title: 书名
            stage: 阶段名称（analysis, generation, full）
            data: 检查点数据
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")
        checkpoint_file = self.checkpoint_dir / f"{safe_title}_{stage}.json"

        try:
            data["checkpoint_time"] = datetime.now().isoformat()
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 检查点已保存: {checkpoint_file}")
        except Exception as e:
            logger.error(f"❌ 保存检查点失败: {e}")

    def load_checkpoint(self, book_title: str, stage: str) -> Optional[Dict]:
        """
        加载检查点

        Args:
            book_title: 书名
            stage: 阶段名称

        Returns:
            检查点数据，如果不存在返回 None
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")
        checkpoint_file = self.checkpoint_dir / f"{safe_title}_{stage}.json"

        if not checkpoint_file.exists():
            return None

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ 加载检查点失败: {e}")
            return None

    def get_remaining_chunks(self, book_title: str, all_chunks: List[Dict]) -> List[Dict]:
        """
        获取剩余未分析的 chunk

        Args:
            book_title: 书名
            all_chunks: 所有 chunk 列表

        Returns:
            未分析的 chunk 列表
        """
        checkpoint = self.load_checkpoint(book_title, "analysis")
        if not checkpoint:
            return all_chunks

        analyzed_count = checkpoint.get("chunks_analyzed", 0)
        return all_chunks[analyzed_count:]

    def can_skip_analysis(self, book_title: str) -> bool:
        """
        检查是否可以跳过分析阶段

        Args:
            book_title: 书名

        Returns:
            是否可以跳过
        """
        checkpoint = self.load_checkpoint(book_title, "analysis")
        return checkpoint is not None and checkpoint.get("status") == "complete"

    def can_recover(self, book_title: str) -> bool:
        """
        检查是否可以恢复

        Args:
            book_title: 书名

        Returns:
            是否存在可恢复的检查点
        """
        # 检查任一阶段的检查点
        for stage in ["analysis", "generation", "full"]:
            if self.load_checkpoint(book_title, stage):
                return True
        return False

    def get_recovery_info(self, book_title: str) -> Optional[Dict]:
        """
        获取恢复信息

        Args:
            book_title: 书名

        Returns:
            恢复信息
        """
        # 优先返回完整的检查点
        for stage in ["full", "generation", "analysis"]:
            checkpoint = self.load_checkpoint(book_title, stage)
            if checkpoint:
                checkpoint["stage"] = stage
                return checkpoint
        return None

    def clean_checkpoints(self, book_title: str) -> None:
        """
        清理检查点

        Args:
            book_title: 书名
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")

        for checkpoint_file in self.checkpoint_dir.glob(f"{safe_title}_*.json"):
            try:
                checkpoint_file.unlink()
                logger.info(f"🗑️ 已清理检查点: {checkpoint_file}")
            except Exception as e:
                logger.error(f"❌ 清理检查点失败: {e}")


# 阶段1: 分析提示词
ANALYSIS_PROMPT = """请分析书籍内容，输出结构化分析（不生成最终 wiki 内容）。

【书籍信息】
书名：{book_title}
作者：{author}

【内容摘要】
{content_summary}

【分析要求】
1. 提取关键实体、概念、核心论点
2. 识别与已有知识的连接（如果有）
3. 检测矛盾、张力或争议点
4. 推荐 wiki 结构（章节、概念、案例等）

输出 JSON 格式：
{{
  "key_entities": ["实体1", "实体2"],
  "key_concepts": [
    {{"name": "概念名", "definition": "定义", "relevance": "重要性"}}
  ],
  "core_arguments": ["论点1", "论点2"],
  "connections_to_existing": ["与现有概念的联系"],
  "contradictions": ["内部矛盾或张力"],
  "recommended_structure": {{
    "chapters": ["章节建议"],
    "concepts": ["应提取的概念"],
    "cases": ["应提取的案例"]
  }}
}}

【约束】
- 禁止占位符
- 必须输出有效 JSON
"""

# 阶段2: 生成提示词（基于分析结果）
GENERATION_PROMPT = """根据分析结果，生成书籍知识图谱。

【书籍信息】
书名：{book_title}
作者：{author}
学科：{discipline}

【分析结果】
{analysis_json}

【生成要求】
基于分析结果，生成完整的 JSON 输出，包含以下字段：
{{
  "metadata": {{
    "title": "书名",
    "author": "作者",
    "author_intro": "作者简介",
    "discipline": "学科",
    "tags": ["标签"]
  }},
  "time_background": {{
    "macro_background": "宏观背景",
    "micro_background": "微观背景",
    "core_contradiction": "核心矛盾"
  }},
  "chapters": [
    {{
      "chapter_number": "1",
      "title": "标题",
      "core_argument": "核心论点",
      "underlying_logic": "前提假设→推理链条→核心结论"
    }}
  ],
  "core_concepts": [
    {{
      "name": "概念名",
      "definition": "定义",
      "deep_meaning": "深层含义"
    }}
  ],
  "key_insights": [],
  "key_cases": [],
  "key_quotes": [],
  "critical_analysis": {{
    "feminist_perspective": "",
    "postcolonial_perspective": ""
  }}
}}

【约束】
- 禁止占位符
- 禁止合并章节
- 必须输出纯 JSON
"""


class TwoStageIngest:
    """
    两阶段摄取处理器

    支持检查点保存和恢复，确保失败时不会丢失已分析的结果
    """

    def __init__(self, llm_client, checkpoint_dir: Optional[str] = None):
        self.llm_client = llm_client
        self.cache = get_cache()
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path("cache/checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, book_title: str, stage: str, data: Dict) -> None:
        """
        保存检查点

        Args:
            book_title: 书名
            stage: 阶段名称（analysis, generation, full）
            data: 检查点数据
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")
        checkpoint_file = self.checkpoint_dir / f"{safe_title}_{stage}.json"

        try:
            data["checkpoint_time"] = datetime.now().isoformat()
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 检查点已保存: {checkpoint_file}")
        except Exception as e:
            logger.error(f"❌ 保存检查点失败: {e}")

    def load_checkpoint(self, book_title: str, stage: str) -> Optional[Dict]:
        """
        加载检查点

        Args:
            book_title: 书名
            stage: 阶段名称

        Returns:
            检查点数据，如果不存在返回 None
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")
        checkpoint_file = self.checkpoint_dir / f"{safe_title}_{stage}.json"

        if not checkpoint_file.exists():
            return None

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ 加载检查点失败: {e}")
            return None

    def get_remaining_chunks(self, book_title: str, all_chunks: List[Dict]) -> List[Dict]:
        """
        获取剩余未分析的 chunk

        Args:
            book_title: 书名
            all_chunks: 所有 chunk 列表

        Returns:
            未分析的 chunk 列表
        """
        checkpoint = self.load_checkpoint(book_title, "analysis")
        if not checkpoint:
            return all_chunks

        analyzed_count = checkpoint.get("chunks_analyzed", 0)
        return all_chunks[analyzed_count:]

    def can_skip_analysis(self, book_title: str) -> bool:
        """
        检查是否可以跳过分析阶段

        Args:
            book_title: 书名

        Returns:
            是否可以跳过
        """
        checkpoint = self.load_checkpoint(book_title, "analysis")
        return checkpoint is not None and checkpoint.get("status") == "complete"

    def can_recover(self, book_title: str) -> bool:
        """
        检查是否可以恢复

        Args:
            book_title: 书名

        Returns:
            是否存在可恢复的检查点
        """
        # 检查任一阶段的检查点
        for stage in ["analysis", "generation", "full"]:
            if self.load_checkpoint(book_title, stage):
                return True
        return False

    def get_recovery_info(self, book_title: str) -> Optional[Dict]:
        """
        获取恢复信息

        Args:
            book_title: 书名

        Returns:
            恢复信息
        """
        # 优先返回完整的检查点
        for stage in ["full", "generation", "analysis"]:
            checkpoint = self.load_checkpoint(book_title, stage)
            if checkpoint:
                checkpoint["stage"] = stage
                return checkpoint
        return None

    def clean_checkpoints(self, book_title: str) -> None:
        """
        清理检查点

        Args:
            book_title: 书名
        """
        safe_title = book_title.replace("/", "_").replace("\\", "_")

        for checkpoint_file in self.checkpoint_dir.glob(f"{safe_title}_*.json"):
            try:
                checkpoint_file.unlink()
                logger.info(f"🗑️ 已清理检查点: {checkpoint_file}")
            except Exception as e:
                logger.error(f"❌ 清理检查点失败: {e}")

    def _get_analysis_cache_key(self, book_title: str, content_hash: str) -> str:
        """生成分析缓存键"""
        return f"analysis_{book_title}_{content_hash[:12]}"

    async def analyze(self, book_title: str, author: str, content_summary: str) -> Optional[Dict]:
        """
        阶段1: 分析书籍内容
        """
        # 计算内容哈希用于缓存
        content_hash = hashlib.md5(content_summary.encode()).hexdigest()
        cache_key = self._get_analysis_cache_key(book_title, content_hash)

        # 检查缓存
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"使用分析缓存: {cache_key}")
            return cached

        # 调用 LLM 分析
        prompt = ANALYSIS_PROMPT.format(
            book_title=book_title,
            author=author,
            content_summary=content_summary[:5000]  # 限制长度
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self.llm_client._call_llm, messages, max_tokens=4096),
                timeout=180
            )

            if response:
                # 提取 JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    analysis = json.loads(json_match.group())
                    # 保存缓存
                    self.cache.set(cache_key, analysis)
                    return analysis

        except Exception as e:
            logger.warning(f"分析失败: {e}")

        return None

    async def generate(self, book_title: str, author: str, discipline: str, analysis: Dict) -> Optional[Dict]:
        """
        阶段2: 基于分析生成知识图谱
        """
        analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)

        prompt = GENERATION_PROMPT.format(
            book_title=book_title,
            author=author,
            discipline=discipline,
            analysis_json=analysis_json[:8000]  # 限制长度
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self.llm_client._call_llm, messages, max_tokens=16384),
                timeout=300
            )

            if response:
                # 提取 JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    return json.loads(json_match.group())

        except Exception as e:
            logger.warning(f"生成失败: {e}")

        return None

    async def process(self, book_title: str, author: str, discipline: str, content_summary: str) -> Optional[Dict]:
        """
        完整的两阶段摄取流程
        """
        logger.info(f"阶段1: 分析 {book_title}...")
        analysis = await self.analyze(book_title, author, content_summary)

        if not analysis:
            logger.error(f"分析失败")
            return None

        logger.info(f"阶段2: 生成知识图谱...")
        result = await self.generate(book_title, author, discipline, analysis)

        return result
