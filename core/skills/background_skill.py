"""
时代背景 Skill

从书籍内容中提取时代背景信息：
- 宏观历史背景
- 微观作者背景
- 核心矛盾
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class BackgroundSkill(BaseSkill):
    """时代背景 Skill"""

    name = "background"
    section_name = "时代背景"
    output_field = "time_background"
    min_items = 1

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中提取时代背景信息。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "time_background": {{    "macro_background": "宏观历史背景（不少于100字，描述写作时代的社会、政治、经济环境）",    "micro_background": "微观作者背景（不少于80字，描述作者的个人经历、学术背景、写作动机）",    "core_contradiction": "核心矛盾（不少于50字，描述书籍试图解决的核心问题或时代矛盾）"  }},  "author_intro": "作者简介（不少于100字）"}}
}}

【核心约束 - 最高优先级】
1. **宏观背景**：
   - 必须结合书籍出版年代
   - 描述当时的社会思潮、政治环境、学术氛围

2. **微观背景**：
   - 必须包含作者的学术背景
   - 分析写作动机和目的

3. **核心矛盾**：
   - 必须是书籍试图回答的核心问题
   - 不能是泛泛而谈

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["time_background", "author_intro"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验时代背景结果"""
        errors = []

        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        if "time_background" not in result:
            errors.append("缺失字段: time_background")

        background = result.get("time_background", {})

        # 检查宏观背景
        macro = background.get("macro_background", "")
        if len(macro) < 100:
            errors.append(f"宏观背景过短: {len(macro)} < 100")

        # 检查微观背景
        micro = background.get("micro_background", "")
        if len(micro) < 80:
            errors.append(f"微观背景过短: {len(micro)} < 80")

        # 检查核心矛盾
        contradiction = background.get("core_contradiction", "")
        if len(contradiction) < 50:
            errors.append(f"核心矛盾过短: {len(contradiction)} < 50")

        return len(errors) == 0, errors

    def generate_markdown(self, result: Dict) -> str:
        """生成时代背景 Markdown"""
        lines = []

        background = result.get("time_background", {})
        author_intro = result.get("author_intro", "")

        if not background:
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 时代背景提取异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        # 作者简介（更新到开头）
        if author_intro:
            lines.append(f"> [!info] 作者简介")
            lines.append(f"> {author_intro}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # 时代背景
        lines.append("## 📜 时代背景")
        lines.append("")

        macro = background.get("macro_background", "")
        if macro:
            lines.append(f"> [!quote] 宏观背景")
            lines.append(f"> {macro}")
            lines.append("")

        micro = background.get("micro_background", "")
        if micro:
            lines.append(f"> [!note] 微观背景")
            lines.append(f"> {micro}")
            lines.append("")

        contradiction = background.get("core_contradiction", "")
        if contradiction:
            lines.append("### 核心矛盾")
            lines.append("")
            lines.append(contradiction)
            lines.append("")

        lines.append("---")
        lines.append("")

        return "\n".join(lines)