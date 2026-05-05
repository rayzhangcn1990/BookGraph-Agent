"""提示词定义模块"""
SYSTEM_PROMPT = """你是一位专业的学术书籍分析专家，精通知识图谱构建。你的任务是对书籍内容进行深度分析，输出结构化的知识图谱数据。

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"、"（内容由模型生成）"等无意义说明
3. 所有内容必须有实质性信息，如果确实无法分析某项，请基于上下文合理推断并明确标注
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力
6. 所有关联书籍必须说明具体的关联维度

【分析标准】
1. 对核心理论，必须拆解底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
2. 对涉及发展演化的内容，必须输出：各阶段特点、消亡/进化的原因与解释、发展的核心动力分析
3. 对金句必须进行语境化解读，区分字面意义与深层含义，识别常见误读
4. 批判性分析必须引入多元视角（女性主义、后殖民主义、制度经济学等）
5. 所有关联书籍必须说明关联的具体维度

【输出质量要求】
- 所有内容必须完整、具体、有信息量
- 避免模糊、笼统、空洞的表述
- 每个概念、洞见、案例都必须有实质性的分析和解读
- 如果某项内容确实无法从书中提取，请明确说明"书中未涉及此项内容"并跳过

输出格式：严格按照提供的 JSON Schema 输出，不添加任何额外说明。"""


CHUNK_ANALYSIS_PROMPT = """请分析以下书籍内容，提取结构化信息。

【书籍信息】
书名：{book_title}

【完整内容】
{chunk_content}

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"等无意义说明
3. 所有内容必须有实质性信息
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力

【输出格式示例 - 严格按照此格式】
{{
  "chapter_summaries": [
    {{
      "chapter_number": "1",
      "title": "章节实际标题",
      "core_argument": "本章的核心论点（必须有实质内容）",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "related_books": ["关联书籍名称"],
      "critical_questions": ["批判性问题1", "批判性问题2"]
    }}
  ],
  "core_concepts": [
    {{
      "name": "概念名称",
      "definition": "概念的明确定义",
      "deep_meaning": "深层含义分析",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "development_stages": [{{"name": "阶段名", "period": "时期", "characteristics": "特点", "evolution_reason": "演化原因"}}],
      "core_drivers": ["驱动因素1", "驱动因素2"],
      "critical_review": "批判性审视内容",
      "related_books": ["关联书籍"]
    }}
  ],
  "key_insights": [
    {{
      "title": "洞见标题",
      "description": "洞见描述",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "deep_assumptions": ["假设1", "假设2"],
      "controversies": "潜在争议分析",
      "multi_perspectives": {{\"视角名\": "解读内容"}}
    }}
  ],
  "key_cases": [
    {{
      "name": "案例名称",
      "source_chapter": "来源章节",
      "event_description": "事件描述",
      "development_stages": [{{"name": "阶段名", "description": "描述"}}],
      "core_drivers": ["驱动因素"],
      "historical_limitations": "历史局限分析"
    }}
  ],
  "key_quotes": [
    {{
      "text": "原文金句（必须是书中实际内容）",
      "chapter": "来源章节",
      "core_theme": "核心主题",
      "background_context": "时代背景",
      "underlying_logic": "前提假设：...→推理链条：...→核心结论：...",
      "common_misreading": "常见误读（可选）",
      "related_books": ["关联书籍"]
    }}
  ]
}}

【分析要求】
请分析整本书的内容，提取以下信息（以 JSON 格式输出）：

1. 章节摘要：识别书中的所有章节，对每章提取：
   - chapter_number: 章节编号
   - title: 章节标题
   - core_argument: 核心论点（一句话概括，必须有实质内容）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - related_books: 关联书籍（如有提及）
   - critical_questions: 批判性问题（2-3 个，必须具体）

2. 核心概念：提取关键概念，对每个概念提取：
   - name: 概念名称
   - definition: 定义（必须有实质性内容，不能是占位符）
   - deep_meaning: 深层含义（必须具体分析）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - development_stages: 发展阶段（如有，包含阶段名称、时期、特点、消亡/进化原因）
   - core_drivers: 发展核心动力（数组，每项必须有实质内容）
   - critical_review: 批判性审视（必须具体分析，不能是占位符）
   - related_books: 关联书籍（如有）

3. 关键洞见：识别作者的重要观点，对每个洞见提取：
   - title: 洞见标题
   - description: 描述（必须有实质性内容）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - deep_assumptions: 深层假设列表（每项必须具体）
   - controversies: 潜在争议（必须具体分析）
   - multi_perspectives: 多维审视（不同视角的具体解读）

4. 关键案例：提取书中的具体案例，对每个案例提取：
   - name: 案例名称
   - source_chapter: 来源章节
   - event_description: 事件描述（必须具体详细）
   - development_stages: 发展阶段（每项必须包含名称和描述）
   - core_drivers: 发展核心动力（数组，每项必须具体）
   - historical_limitations: 历史局限性（必须具体分析）

5. 金句：摘录有代表性的原文语句，对每句提取：
   - text: 原文（必须是书中实际内容）
   - chapter: 来源章节
   - core_theme: 核心主题
   - background_context: 时代背景关联（必须具体）
   - underlying_logic: 底层逻辑（必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]）
   - common_misreading: 常见误读（如有）
   - related_books: 关联书籍（如有）

请以 JSON 格式输出，不要添加任何额外说明。所有内容必须有实质性信息，严禁使用占位符。"""

# 🔑 优化：批量 Chunk 分析提示词（减少 API 调用次数）
BATCH_CHUNK_ANALYSIS_PROMPT = """请分析以下多个书籍内容块，提取结构化信息。

【书籍信息】
书名：{book_title}

【内容块列表】
以下内容按块分隔，每个块用 "--- CHUNK BREAK ---" 标记边界：

{batch_content}

【核心约束 - 必须遵守】
1. 严禁输出"待分析"、"待补充"、"待填写"、"待生成"、"TBD"、"TODO"、"N/A"等占位符
2. 严禁输出"（此处内容由 LLM 生成）"等无意义说明
3. 所有内容必须有实质性信息
4. 对于底层逻辑，必须使用单行箭头格式：前提假设：[内容]→推理链条：[内容]→核心结论：[内容]
5. 对于发展演化，必须完整输出：阶段特点、消亡/进化原因、发展核心动力

【分析要求】
请分析所有内容块，提取以下信息（以 JSON 格式输出）：

输出格式：
{{"chunks_analysis": [
    {{ "chunk_index": 0,
      "chapter_summaries": [...],
      "core_concepts": [...],
      "key_insights": [...],
      "key_cases": [...],
      "key_quotes": [...]
    }},
    {{ "chunk_index": 1,
      ...
    }}
  ]
}}

请以 JSON 格式输出，不要添加任何额外说明。所有内容必须有实质性信息，严禁使用占位符。"""

SYNTHESIS_PROMPT = """请将以下所有分析结果综合为完整的书籍知识图谱。

【书籍信息】
书名：{book_title}
作者：{author}

【章节列表（JSON数组 - 必须完整复制）】
{chapters_list}

🔴 **CRITICAL TECHNICAL INSTRUCTION**：
上述 JSON 数组包含 {chapters_count} 个章节对象。
你必须将其 **完整复制** 到输出的 `chapters` 字段，遵守以下技术规范：

1. **禁止使用注释**：JSON 不支持 `//` 注释，你的输出必须是无注释的有效 JSON
2. **禁止省略内容**：不允许写 "此处省略"、"实际输出时请完整复制" 等说明
3. **禁止修改结构**：保持原有的 chapter_number、title、core_argument 等字段结构
4. **必须完整输出**：所有 {chapters_count} 个章节都必须出现在最终输出的 chapters 数组中

正确示例：
```json
"chapters": [
  {"chapter_number": "1", "title": "第一章", "core_argument": "...", ...},
  {"chapter_number": "2", "title": "第二章", "core_argument": "...", ...},
  ...（全部章节）
]
```

错误示例（会导致解析失败）：
```json
"chapters": [
  // 此处省略，请完整复制（❌ JSON不支持注释）
  {"chapter_number": "N/A", "title": "示例"...} // ❌ 这是错误做法
]
```

【分析结果】
{all_chunk_analyses}

【综合要求】
请生成完整的 BookGraph JSON，包含以下部分：

1. metadata: 书籍元数据
   - title: 字符串
   - author: 字符串
   - author_intro: 字符串（作者简介）
   - year_published: 字符串或 null
   - category: 字符串数组
   - discipline: 字符串（一级学科，从以下选择：政治学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术）
   - sub_discipline: 字符串或 null（二级子学科，如政治学下的：政治哲学、比较政治、国际关系等）
   - tags: 字符串数组
   - related_books: 字符串数组

2. time_background: 时代背景
   - macro_background: 字符串
   - micro_background: 字符串
   - core_contradiction: 字符串

3. chapters: 章节摘要数组
   **🔴 必须完整复制上述【章节列表】中的 {chapters_count} 个章节！**
   - chapter_number: 字符串
   - title: 字符串
   - core_argument: 字符串
   - underlying_logic: 字符串
   - related_books: 字符串数组
   - critical_questions: 字符串数组

4. core_concepts: 核心概念数组，每项包含：
   - name: 字符串
   - definition: 字符串
   - deep_meaning: 字符串
   - underlying_logic: 字符串
   - development_stages: 数组，每项为对象{{"name": "...", "period": "...", "characteristics": "...", "evolution_reason": "..."}}
   - core_drivers: 字符串数组
   - critical_review: 字符串
   - related_books: 字符串数组

5. key_insights: 关键洞见数组，每项包含：
   - title: 字符串
   - description: 字符串
   - underlying_logic: 字符串
   - deep_assumptions: 字符串数组
   - related_books: 字符串数组
   - controversies: 字符串
   - multi_perspectives: 对象，键为视角名称，值为解读字符串

6. key_cases: 关键案例数组，每项包含：
   - name: 字符串
   - source_chapter: 字符串
   - event_description: 字符串
   - development_stages: 数组，每项为对象{{"name": "...", "description": "..."}}
   - core_drivers: 字符串数组
   - related_books: 字符串数组
   - historical_limitations: 字符串

7. key_quotes: 金句数组，每项包含：
   - text: 字符串
   - chapter: 字符串
   - core_theme: 字符串
   - background_context: 字符串
   - underlying_logic: 字符串
   - common_misreading: 字符串或 null
   - related_books: 字符串数组

8. critical_analysis: 批判性分析
   - core_doubts: 数组，每项为对象{{"question": "...", "analysis": "..."}}
   - feminist_perspective: 字符串
   - postcolonial_perspective: 字符串
   - ethical_boundaries: 对象{{"reasonable": "...", "dangerous": "...", "institutional_safeguards": "..."}}

9. learning_path: 学习路径对象
   - beginner: 字符串数组
   - intermediate: 字符串数组
   - advanced: 字符串数组
   - practice: 字符串数组

10. book_network: 对象，键为书名，值为关联维度说明字符串

【重要格式要求】
- 必须输出有效的 JSON 格式
- 所有字段类型必须正确（字符串、数组、对象）
- 不要使用 Markdown 代码块包裹
- 不要添加任何额外说明文字

请严格按照上述格式输出完整的 JSON。"""


DISCIPLINE_DETECTION_PROMPT = """请判断以下书籍所属的学科类别。

【书籍信息】
书名：{book_title}
作者：{author}

【内容样本】
{first_chapter_content}

【可选一级学科类别】
政治学、经济学、心理学、历史学、哲学、管理学、社会学、文学、科学、技术

【政治学的子学科示例】
政治哲学、比较政治、国际关系、政治经济学、公共行政、政治理论

请从一级学科类别中选择最匹配的一个，如能确定子学科也可一并输出。
输出格式：一级学科名称 或 一级学科名称/子学科名称（如：政治学/政治哲学）
仅输出学科名称，不要添加任何额外说明。"""


DISCIPLINE_GRAPH_UPDATE_PROMPT = """请将新书的内容整合到现有学科图谱中。

【现有学科图谱】
{existing_discipline_graph}

【新书知识图谱】
{new_book_graph}

【新书书名】
{book_title}

【更新要求】
1. 整合新书的核心概念到学科概念体系
2. 更新学科核心思想（如有新的贡献）
3. 在书籍网络中添加新书节点，并说明与已有书籍的关联关系
4. 如有新的学科发展洞见，更新发展脉络
5. 更新概念词汇库

请输出更新后的完整学科图谱内容（Markdown 格式）。"""


