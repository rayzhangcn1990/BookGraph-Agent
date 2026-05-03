"""
金句萃取 Skill

从书籍内容中提取金句：
- 原文金句
- 来源章节
- 核心主题
- 时代背景
- 底层逻辑
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class QuoteSkill(BaseSkill):
    """金句萃取 Skill"""

    name = "quote"
    section_name = "金句萃取"
    output_field = "key_quotes"
    min_items = 3

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中提取金句。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "key_quotes": [    {{      "text": "原文金句（必须是书中实际内容）",      "chapter": "来源章节",      "core_theme": "核心主题",      "background_context": "时代背景关联（具体分析）",      "underlying_logic": "前提假设：[内容]→推理链条：[内容]→核心结论：[内容]",      "common_misreading": "常见误读（可选）",      "related_books": ["关联书籍"]    }}  ]
}}

【核心约束 - 最高优先级】
1. **金句真实性**：
   - 金句必须来自书中原文，不能是编造或概括
   - 保留原文表述，不要修改

2. **语境化解读**：
   - 时代背景必须有具体分析，不能是模板化表述
   - 底层逻辑必须完整拆解

3. **数量要求**：
   - 提取至少3条金句
   - 金句应具有代表性或理论价值

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["key_quotes"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验金句结果"""
        errors = []

        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        if "key_quotes" not in result:
            errors.append("缺失字段: key_quotes")

        quotes = result.get("key_quotes", [])

        if len(quotes) < self.min_items:
            if result.get("extraction_status") == "failed":
                return False, errors
            errors.append(f"金句数量不足: {len(quotes)} < {self.min_items}")

        for i, quote in enumerate(quotes):
            # 文本校验
            text = quote.get("text", "")
            if len(text) < 10:
                errors.append(f"金句{i+1} 文本过短")

            # 时代背景校验
            background = quote.get("background_context", "")
            if len(background) < 20:
                errors.append(f"金句{i+1} 缺乏时代背景分析")

        return len(errors) == 0, errors

    def generate_markdown(self, result: Dict) -> str:
        """生成金句 Markdown"""
        lines = []

        quotes = result.get("key_quotes", [])

        if not quotes:
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 金句萃取异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        for quote in quotes:
            text = quote.get("text", "")
            chapter = quote.get("chapter", "")
            theme = quote.get("core_theme", "")
            background = quote.get("background_context", "")
            logic = quote.get("underlying_logic", "")
            misreading = quote.get("common_misreading", "")
            related = quote.get("related_books", [])

            lines.append(f"> \"{text}\"")
            lines.append(f"> —— 《{chapter}》")
            lines.append("")

            lines.append("| 要素 | 内容 |")
            lines.append("|------|------|")
            lines.append(f"| 核心主题 | {theme} |")
            lines.append(f"| 时代背景 | {background} |")

            if logic:
                lines.append(f"| 底层逻辑 | {logic} |")

            if misreading:
                lines.append(f"| 常见误读 | {misreading} |")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)