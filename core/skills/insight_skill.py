"""
关键洞见提取 Skill

从书籍内容中提取关键洞见：
- 洞见标题
- 洞见描述
- 底层逻辑
- 深层假设
- 多维审视
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class InsightSkill(BaseSkill):
    """关键洞见提取 Skill"""

    name = "insight"
    section_name = "关键洞见"
    output_field = "key_insights"
    min_items = 2

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中提取关键洞见。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "key_insights": [    {{      "title": "洞见标题",      "description": "洞见描述（必须有实质内容）",      "underlying_logic": "前提假设：[内容]→推理链条：[内容]→核心结论：[内容]",      "deep_assumptions": ["深层假设1", "深层假设2"],      "related_books": ["关联书籍"],      "controversies": "潜在争议分析",      "multi_perspectives": {{        "女性主义视角": "解读内容",        "后殖民主义视角": "解读内容"      }}    }}  ]
}}

【核心约束 - 最高优先级】
1. **洞见质量**：
   - 洞见必须是作者的重要观点或理论贡献
   - 描述必须有实质内容，不能是模板化表述

2. **底层逻辑**：
   - 必须使用单行箭头格式

3. **多维审视**：
   - 至少提供2个不同视角的解读
   - 每个视角必须有具体分析内容

4. **数量要求**：
   - 提取至少2个关键洞见

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["key_insights"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验洞见结果"""
        errors = []

        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        if "key_insights" not in result:
            errors.append("缺失字段: key_insights")

        insights = result.get("key_insights", [])

        if len(insights) < self.min_items:
            if result.get("extraction_status") == "failed":
                return False, errors
            errors.append(f"洞见数量不足: {len(insights)} < {self.min_items}")

        for i, insight in enumerate(insights):
            # 描述校验
            desc = insight.get("description", "")
            if len(desc) < 20:
                errors.append(f"洞见{i+1} 描述过短")

            # 多维审视校验
            perspectives = insight.get("multi_perspectives", {})
            if len(perspectives) < 2:
                errors.append(f"洞见{i+1} 多维审视不足")

        return len(errors) == 0, errors

    def generate_markdown(self, result: Dict) -> str:
        """生成洞见 Markdown"""
        lines = []

        insights = result.get("key_insights", [])

        if not insights:
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 关键洞见解析异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        for insight in insights:
            title = insight.get("title", "未命名洞见")
            desc = insight.get("description", "")
            logic = insight.get("underlying_logic", "")
            assumptions = insight.get("deep_assumptions", [])
            perspectives = insight.get("multi_perspectives", {})
            controversies = insight.get("controversies", "")

            lines.append(f"### {title}")
            lines.append("")
            lines.append(f"{desc}")
            lines.append("")

            if logic:
                lines.append("**底层逻辑**：")
                lines.append("")
                m = re.match(r'前提假设：(.+?)\s*→\s*推理链条：(.+?)\s*→\s*核心结论：(.+)$', logic)
                if m:
                    lines.append(f"- **前提假设**：{m.group(1).strip()}")
                    lines.append(f"- **推理链条**：{m.group(2).strip()}")
                    lines.append(f"- **核心结论**：{m.group(3).strip()}")
                else:
                    lines.append(f"- {logic}")
                lines.append("")

            if assumptions:
                lines.append("**深层假设**：")
                for assumption in assumptions:
                    lines.append(f"- {assumption}")
                lines.append("")

            if perspectives:
                lines.append("**多维审视**：")
                lines.append("")
                lines.append("| 视角 | 解读 |")
                lines.append("|------|------|")
                for perspective, interpretation in perspectives.items():
                    lines.append(f"| {perspective} | {interpretation} |")
                lines.append("")

            if controversies:
                lines.append(f"> [!question] 潜在争议")
                lines.append(f"> {controversies}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)