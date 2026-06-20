"""
两阶段摄取提示词定义（优化版）

ponytail: 阶段1输出生成指令而非数据，真正分离关注点
"""

# ponytail: 阶段1: 分析提示词（优化版：输出生成指令而非数据）
ANALYSIS_PROMPT = """请分析书籍内容，输出生成指令（而非数据）。

【书籍信息】
书名：{book_title}
作者：{author}

【内容摘要】
{content_summary}

【分析要求】
分析书籍内容，输出结构化的**生成指令**（指导阶段2如何生成知识图谱）：

输出 JSON 格式：
{{
  "generation_instructions": {{
    "chapters": {{
      "count": "提取5-10个核心章节",
      "focus": "保留底层逻辑格式（前提假设→推理链条→核心结论）",
      "avoid": "禁止章节编号合并（如'11-22'）"
    }},
    "concepts": {{
      "count": "提取3-5个核心概念",
      "depth": "定义需超过30字，包含深层含义"
    }},
    "insights": {{
      "count": "提取2-4个关键洞见",
      "format": "包含标题、描述、底层逻辑、争议点"
    }},
    "cases": {{
      "count": "提取1-3个关键案例",
      "fields": "必须包含名称、来源章节、事件描述"
    }},
    "quotes": {{
      "count": "提取3-5条金句",
      "fields": "必须包含文本、章节、背景语境、底层逻辑"
    }},
    "critical_analysis": {{
      "perspectives": ["女性主义视角", "后殖民主义视角"],
      "depth": "每视角分析需超过50字"
    }}
  }},
  "content_highlights": {{
    "key_entities": ["识别的核心实体（供参考）"],
    "key_arguments": ["识别的核心论点（供参考）"],
    "contradictions": ["内部矛盾或张力（供参考）"]
  }}
}}

【约束】
- 输出生成指令（而非数据）
- 指令应具体、可执行
- 禁止占位符
"""

# ponytail: 阶段2: 生成提示词（基于生成指令）
GENERATION_PROMPT = """根据生成指令，生成书籍知识图谱。

【书籍信息】
书名：{book_title}
作者：{author}
学科：{discipline}

【生成指令】
{generation_instructions}

【参考信息】
{content_highlights}

【生成要求】
严格按照生成指令执行：

1. **章节生成**
   - 按指令中的count提取章节数量
   - 每章节包含：chapter_number, title, core_argument, underlying_logic
   - underlying_logic格式：前提假设→推理链条→核心结论

2. **概念生成**
   - 按指令中的count提取概念数量
   - 每概念包含：name, definition（>30字）, deep_meaning

3. **洞见生成**
   - 按指令中的count提取洞见数量
   - 每洞见包含：title, description, underlying_logic, controversies

4. **案例生成**
   - 按指令中的count提取案例数量
   - 每案例包含：name, source_chapter, event_description

5. **金句生成**
   - 按指令中的count提取金句数量
   - 每金句包含：text, chapter, background_context, underlying_logic

6. **批判性分析**
   - 按指令中的perspectives生成分析
   - 每视角分析>50字

输出完整 JSON：
{{
  "metadata": {{...}},
  "time_background": {{...}},
  "chapters": [...],
  "core_concepts": [...],
  "key_insights": [...],
  "key_cases": [...],
  "key_quotes": [...],
  "critical_analysis": {{...}}
}}

【约束】
- 严格遵守生成指令
- 禁止占位符
- 禁止章节合并
"""
