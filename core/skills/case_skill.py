"""
关键案例提取 Skill

从书籍内容中提取关键案例：
- 案例名称
- 事件描述
- 发展阶段
- 核心动力
- 历史局限
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class CaseSkill(BaseSkill):
    """关键案例提取 Skill"""

    name = "case"
    section_name = "关键案例"
    output_field = "key_cases"
    min_items = 1

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中提取关键案例。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "key_cases": [    {{      "name": "案例名称",      "source_chapter": "来源章节",      "event_description": "事件描述（详细，不少于50字）",      "development_stages": "发展阶段描述（单行文本，用分号分隔）",      "core_drivers": "核心动力（用逗号分隔）",      "related_books": "关联书籍（用逗号分隔）",      "historical_limitations": "历史局限性分析（不少于20字）"    }}  ]
}}

【核心约束 - 最高优先级】
1. **简化格式**：
   - 发展阶段和核心动力使用单行文本格式，不要用嵌套数组
   - 用分号或逗号分隔多个项目

2. **案例质量**：
   - 案例必须是书中具体提及的历史事件、研究案例或典型案例
   - 事件描述必须详细具体

3. **历史局限**：
   - 必须分析案例的历史局限性

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["key_cases"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验案例结果"""
        errors = []

        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        if "key_cases" not in result:
            errors.append("缺失字段: key_cases")

        cases = result.get("key_cases", [])

        if len(cases) < self.min_items:
            if result.get("extraction_status") == "failed":
                return False, errors
            errors.append(f"案例数量不足: {len(cases)} < {self.min_items}")

        for i, case in enumerate(cases):
            # 事件描述校验
            desc = case.get("event_description", "")
            if len(desc) < 50:
                errors.append(f"案例{i+1} 事件描述过短")

            # 历史局限校验
            limitations = case.get("historical_limitations", "")
            if not limitations or len(limitations) < 20:
                errors.append(f"案例{i+1} 缺乏历史局限性分析")

        return len(errors) == 0, errors

    def generate_markdown(
        self,
        result: Dict,
        extractions: List = None  # 🆕 兼容参数
    ) -> str:
        """生成案例 Markdown"""
        lines = []

        cases = result.get("key_cases", [])

        if not cases:
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 关键案例解析异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        for case in cases:
            name = case.get("name", "未命名案例")
            source = case.get("source_chapter", "")
            desc = case.get("event_description", "")
            # 🔑 处理简化格式：字符串而非数组
            stages_str = case.get("development_stages", "")
            drivers_str = case.get("core_drivers", "")
            limitations = case.get("historical_limitations", "")

            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"> [!example] 基本信息")
            lines.append(f"> **来源**：{source}")
            lines.append(f"> {desc}")
            lines.append("")

            # 发展阶段（分号分隔）
            if stages_str:
                lines.append("**发展阶段**：")
                lines.append("```")
                stages = stages_str.split(";")
                for j, stage in enumerate(stages, 1):
                    lines.append(f"{j}. {stage.strip()}")
                lines.append("```")
                lines.append("")

            # 核心动力（逗号分隔）
            if drivers_str:
                lines.append(f"**核心动力**：{drivers_str}")
                lines.append("")

            if limitations:
                lines.append(f"> [!warning] 历史局限性")
                lines.append(f"> {limitations}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)