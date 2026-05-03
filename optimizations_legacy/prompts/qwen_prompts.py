"""
针对 Qwen2.5:7B 优化的提示词模板
简洁、结构化、中文优先
"""
from typing import List


class QwenPromptTemplates:
    """Qwen 优化提示词"""

    @staticmethod
    def entity_extraction(text: str, language: str = "zh") -> str:
        """实体提取提示词"""
        if language == "zh":
            return f"""请从以下文本中提取知识图谱的实体和关系。

【要求】
1. 提取关键概念、人物、方法、理论等实体
2. 识别实体之间的关系
3. 用JSON格式输出
4. 每个实体包含：名称、类型、简短定义
5. 每个关系包含：源实体、目标实体、关系类型

【实体类型】
- concept: 概念
- person: 人物
- method: 方法
- theory: 理论
- term: 术语

【关系类型】
- defines: 定义
- includes: 包含
- causes: 导致
- applies_to: 应用于
- related_to: 相关

【输出格式】
```json
{{
  "entities": [
    {{"name": "实体名", "type": "concept", "definition": "简短定义"}}
  ],
  "relations": [
    {{"source": "实体A", "target": "实体B", "type": "includes"}}
  ]
}}
```

【文本内容】
{text}

请严格按JSON格式输出，不要添加其他说明："""
        else:
            return f"""Extract knowledge graph entities and relations from the text.

**Requirements:**
1. Extract key concepts, persons, methods, theories
2. Identify relationships between entities
3. Output in JSON format

**Entity Types:** concept, person, method, theory, term
**Relation Types:** defines, includes, causes, applies_to, related_to

**Output Format:**
```json
{{
  "entities": [
    {{"name": "Entity", "type": "concept", "definition": "Brief definition"}}
  ],
  "relations": [
    {{"source": "Entity A", "target": "Entity B", "type": "includes"}}
  ]
}}
```

**Text:**
{text}

Output JSON only:"""

    @staticmethod
    def batch_extraction(texts: List[str]) -> str:
        """批量提取（小批次）"""
        batch_text = ""
        for i, text in enumerate(texts, 1):
            batch_text += f"\n\n【文本片段{i}】\n{text}"

        return f"""请分别处理以下{len(texts)}个文本片段，提取知识图谱。

为每个片段返回独立的JSON结果。

【输出格式】
```json
{{
  "片段1": {{"entities": [...], "relations": [...]}},
  "片段2": {{"entities": [...], "relations": [...]}}
}}
```

{batch_text}

请严格按JSON格式输出："""

    @staticmethod
    def summarize_section(text: str, max_words: int = 50) -> str:
        """章节摘要"""
        return f"""请用不超过{max_words}字总结以下文本的核心观点。

【文本】
{text}

【要求】
- 提炼最重要的1-2个观点
- 保留关键术语
- 简洁准确

请直接输出摘要："""

    @staticmethod
    def relation_verification(source: str, target: str, context: str) -> str:
        """关系验证"""
        return f"""判断以下两个实体之间是否存在关系。

【实体A】{source}
【实体B】{target}
【上下文】{context}

【输出格式】
```json
{{"has_relation": true/false, "relation_type": "类型", "confidence": 0.0-1.0, "description": "描述"}}
```

请输出JSON："""
