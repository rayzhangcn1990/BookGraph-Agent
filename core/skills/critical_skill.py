"""
批判性分析 Skill

从书籍内容中提取批判性视角：
- 女性主义视角
- 后殖民主义视角
- 核心质疑点
- 伦理边界
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class CriticalSkill(BaseSkill):
    """批判性分析 Skill"""

    name = "critical"
    section_name = "批判性解读"
    output_field = "critical_analysis"
    min_items = 1

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中进行批判性分析。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "critical_analysis": {{    "core_doubts": [      {{        "question": "质疑点（对作者观点的批判性问题）",        "analysis": "分析说明"      }}    ],    "feminist_perspective": "女性主义视角解读（不少于50字）",    "postcolonial_perspective": "后殖民主义视角解读（不少于50字）",    "ethical_boundaries": {{      "reasonable": "合理的伦理边界",      "dangerous": "可能的伦理风险",      "institutional_safeguards": "制度性保障建议"    }}  }}
}}

【核心约束 - 最高优先级】
1. **批判性视角**：
   - 必须从多个视角审视作者观点
   - 女性主义视角要具体分析性别议题
   - 后殖民主义视角要分析西方中心问题

2. **质疑点质量**：
   - 至少提出2个批判性问题
   - 每个问题要有分析说明（不少于30字）

3. **伦理边界**：
   - 明确区分合理与危险的伦理边界
   - 给出具体建议

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["critical_analysis"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验批判性分析结果"""
        errors = []

        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        if "critical_analysis" not in result:
            errors.append("缺失字段: critical_analysis")

        critical = result.get("critical_analysis", {})

        # 检查女性主义视角
        feminist = critical.get("feminist_perspective", "")
        if len(feminist) < 50:
            errors.append(f"女性主义视角过短: {len(feminist)} < 50")

        # 检查后殖民主义视角
        postcolonial = critical.get("postcolonial_perspective", "")
        if len(postcolonial) < 50:
            errors.append(f"后殖民主义视角过短: {len(postcolonial)} < 50")

        # 检查质疑点
        doubts = critical.get("core_doubts", [])
        if len(doubts) < 2:
            errors.append(f"质疑点数量不足: {len(doubts)} < 2")

        return len(errors) == 0, errors

    def generate_markdown(self, result: Dict) -> str:
        """生成批判性分析 Markdown"""
        lines = []

        critical = result.get("critical_analysis", {})

        if not critical:
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 批判性分析异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        # 核心质疑
        doubts = critical.get("core_doubts", [])
        if doubts:
            lines.append("### 核心质疑")
            lines.append("")
            for doubt in doubts:
                question = doubt.get("question", "")
                analysis = doubt.get("analysis", "")
                lines.append(f"- **{question}**")
                if analysis:
                    lines.append(f"  - {analysis}")
            lines.append("")

        # 多元视角
        lines.append("### 多元视角分析")
        lines.append("")

        feminist = critical.get("feminist_perspective", "")
        if feminist:
            lines.append("**女性主义视角**：")
            lines.append(feminist)
            lines.append("")

        postcolonial = critical.get("postcolonial_perspective", "")
        if postcolonial:
            lines.append("**后殖民主义视角**：")
            lines.append(postcolonial)
            lines.append("")

        # 伦理边界
        ethical = critical.get("ethical_boundaries", {})
        if ethical:
            lines.append("---")
            lines.append("")
            lines.append("## ⚖️ 伦理边界")
            lines.append("")
            reasonable = ethical.get("reasonable", "")
            dangerous = ethical.get("dangerous", "")
            safeguards = ethical.get("institutional_safeguards", "")

            if reasonable:
                lines.append(f"> [!success] 合理边界")
                lines.append(f"> {reasonable}")
                lines.append("")

            if dangerous:
                lines.append(f"> [!danger] 潜在风险")
                lines.append(f"> {dangerous}")
                lines.append("")

            if safeguards:
                lines.append(f"> [!tip] 保障建议")
                lines.append(f"> {safeguards}")
                lines.append("")

        return "\n".join(lines)