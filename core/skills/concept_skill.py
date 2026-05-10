"""
核心概念提取 Skill

从书籍内容中提取核心概念：
- 概念名称
- 定义
- 深层含义
- 底层逻辑
- 发展演化
- 批判性审视
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

from core.skills.base_skill import BaseSkill, SkillResult

logger = logging.getLogger("BookGraph-Agent")


class ConceptSkill(BaseSkill):
    """核心概念提取 Skill"""

    name = "concept"
    section_name = "核心概念"
    output_field = "core_concepts"
    min_items = 3

    @property
    def prompt_template(self) -> str:
        return """请从以下书籍内容中提取核心概念。

【书籍信息】
书名：{book_title}

【内容】
{chunk_content}

【输出格式 - 必须严格遵循】
{{  "core_concepts": [    {{      "name": "概念名称",      "definition": "定义（必须有实质内容，不少于20字）",      "deep_meaning": "深层含义分析",      "underlying_logic": "前提假设：[内容]→推理链条：[内容]→核心结论：[内容]",      "development_stages": [        {{          "name": "阶段名称",          "period": "时期",          "characteristics": "阶段特点",          "evolution_reason": "消亡/进化原因"        }}      ],      "core_drivers": ["发展核心动力1", "发展核心动力2"],      "critical_review": "批判性审视（引入多元视角）",      "related_books": ["关联书籍"]    }}  ]
}}

【核心约束 - 最高优先级】
1. **定义质量**：
   - 定义必须有实质内容，不能是"待补充"或简单复述概念名
   - 定义不少于20字，需解释概念本质

2. **底层逻辑**：
   - 必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
   - 每部分必须有实质内容

3. **数量要求**：
   - 提取至少3个核心概念
   - 如果确实无法提取3个，可返回较少数量但需说明原因

4. **关联性**：
   - 概念应来自书籍内容，不是通用百科知识
   - 每个概念应有独特的理论价值

请输出纯 JSON，不要添加任何 Markdown 代码块标记或额外说明。"""

    def get_required_fields(self) -> List[str]:
        return ["core_concepts"]

    def validate(self, result: Dict) -> Tuple[bool, List[str]]:
        """校验概念结果"""
        errors = []

        # Layer 1: 结构校验
        if not result or not isinstance(result, dict):
            return False, ["结果为空或类型错误"]

        # Layer 2: 字段校验
        if "core_concepts" not in result:
            errors.append("缺失字段: core_concepts")

        concepts = result.get("core_concepts", [])

        # Layer 3: 数量校验
        if len(concepts) < self.min_items:
            if result.get("extraction_status") == "failed":
                # 失败状态，跳过
                return False, errors
            errors.append(f"概念数量不足: {len(concepts)} < {self.min_items}")

        # Layer 4: 内容质量校验
        for i, concept in enumerate(concepts):
            # 定义校验
            definition = concept.get("definition", "")
            if len(definition) < 20:
                errors.append(f"概念{i+1} 定义过短: {definition[:20]}")

            # 占位符检测
            if self._has_placeholder(definition):
                errors.append(f"概念{i+1} 定义为占位符")

            # 底层逻辑校验
            logic = concept.get("underlying_logic", "")
            if not self._is_valid_logic_format(logic):
                errors.append(f"概念{i+1} 底层逻辑格式错误")

        return len(errors) == 0, errors

    def generate_markdown(
        self,
        result: Dict,
        extractions: List = None  # 🆕 新增参数（兼容 abstractmethod）
    ) -> str:
        """
        生成概念 Markdown

        🆕 改造：使用 extractions 显示位置引用
        """
        lines = []

        concepts = result.get("core_concepts", [])

        if not concepts:
            status = result.get("extraction_status", "")
            errors = result.get("errors", [])
            lines.append("> [!warning] ⚠️ 核心概念解析异常")
            if errors:
                lines.append(f"> 错误: {', '.join(errors)}")
            return "\n".join(lines)

        # 🆕 构建 extraction 位置映射（用于显示引用）
        extraction_refs = {}
        if extractions:
            for ext in extractions:
                if hasattr(ext, 'extraction_text') and hasattr(ext, 'to_markdown_ref'):
                    extraction_refs[ext.extraction_text] = ext.to_markdown_ref()

        for concept in concepts:
            name = concept.get("name", "未命名概念")
            definition = self._clean_content(concept.get("definition", ""))
            deep_meaning = self._clean_content(concept.get("deep_meaning", ""))
            logic = self._clean_content(concept.get("underlying_logic", ""))
            drivers = concept.get("core_drivers", [])
            stages = concept.get("development_stages", [])
            critical = self._clean_content(concept.get("critical_review", ""))
            related = concept.get("related_books", [])

            # 🆕 尝试获取概念名称的位置引用
            name_ref = extraction_refs.get(name, name)

            lines.append(f"### {name_ref}")
            lines.append("")
            lines.append(f"> [!abstract] 定义")
            # 🆕 尝试获取定义文本的位置引用
            def_ref = extraction_refs.get(definition[:20], definition) if definition and len(definition) > 20 else definition
            lines.append(f"> {def_ref}")
            lines.append("")

            if deep_meaning:
                lines.append(f"**深层含义**：{deep_meaning}")
                lines.append("")

            if logic:
                lines.append("**底层逻辑**：")
                lines.append("")
                # 拆解单行格式
                m = re.match(r'前提假设：(.+?)\s*→\s*推理链条：(.+?)\s*→\s*核心结论：(.+)$', logic)
                if m:
                    lines.append(f"- **前提假设**：{m.group(1).strip()}")
                    lines.append(f"- **推理链条**：{m.group(2).strip()}")
                    lines.append(f"- **核心结论**：{m.group(3).strip()}")
                else:
                    lines.append(f"- {logic}")
                lines.append("")

            if stages:
                lines.append("**发展演化**：")
                lines.append("")
                lines.append("| 阶段 | 时期 | 特点 | 消亡/进化原因 |")
                lines.append("|------|------|------|---------------|")
                for stage in stages:
                    s_name = stage.get("name", "-")
                    s_period = stage.get("period", "-")
                    s_char = stage.get("characteristics", "-")
                    s_reason = stage.get("evolution_reason", "-")
                    lines.append(f"| {s_name} | {s_period} | {s_char} | {s_reason} |")
                lines.append("")

            if drivers:
                lines.append(f"> [!important] 发展核心动力")
                for driver in drivers:
                    lines.append(f"> - {driver}")
                lines.append("")

            if critical:
                lines.append(f"> [!warning] 批判性审视")
                lines.append(f"> {critical}")
                lines.append("")

            if related:
                lines.append(f"**关联书籍**：{', '.join([f'[[{b}]]' for b in related])}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _is_valid_logic_format(self, logic: str) -> bool:
        """校验底层逻辑格式"""
        if not logic:
            return False

        has_premise = "前提假设" in logic or "前提" in logic
        has_chain = "推理链条" in logic or "推理" in logic
        has_conclusion = "核心结论" in logic or "结论" in logic

        return has_premise and has_chain and has_conclusion

    def _has_placeholder(self, content: str) -> bool:
        """检测占位符"""
        placeholders = ["待分析", "待补充", "TBD", "TODO", "N/A", "暂无"]
        for ph in placeholders:
            if ph in content:
                return True
        return False

    def _clean_content(self, content) -> str:
        """清理内容（兼容字典和字符串类型）"""
        if not content:
            return ""

        # 🔑 处理字典类型（可能是LLM返回的非预期格式）
        if isinstance(content, dict):
            # 尝试提取字典中的关键值
            if "text" in content:
                return str(content["text"]).strip()
            if "content" in content:
                return str(content["content"]).strip()
            if "definition" in content:
                return str(content["definition"]).strip()
            # 无关键值，转为字符串表示
            return str(content)[:200]

        # 正常字符串处理
        if isinstance(content, str):
            # 移除占位符
            placeholders = ["待分析", "待补充", "TBD", "TODO", "N/A"]
            for ph in placeholders:
                if content.strip() == ph:
                    return ""
            return content.strip()

        # 其他类型转为字符串
        return str(content)[:200]