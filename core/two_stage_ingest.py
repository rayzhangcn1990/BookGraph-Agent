
"""
两阶段 Chain-of-Thought 摄取 (llm_wiki 改进)
阶段1: 分析 -> 阶段2: 生成
支持增量缓存
"""

import asyncio
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from utils.parse_cache import get_cache

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
    """两阶段摄取处理器"""

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.cache = get_cache()

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
            print(f"   📦 使用分析缓存: {cache_key}")
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
            print(f"   ⚠️ 分析失败: {e}")

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
            print(f"   ⚠️ 生成失败: {e}")

        return None

    async def process(self, book_title: str, author: str, discipline: str, content_summary: str) -> Optional[Dict]:
        """
        完整的两阶段摄取流程
        """
        print(f"   🔍 阶段1: 分析 {book_title}...")
        analysis = await self.analyze(book_title, author, content_summary)

        if not analysis:
            print(f"   ❌ 分析失败")
            return None

        print(f"   📝 阶段2: 生成知识图谱...")
        result = await self.generate(book_title, author, discipline, analysis)

        return result
