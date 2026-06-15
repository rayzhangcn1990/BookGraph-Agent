"""提示词定义模块"""
SYSTEM_PROMPT = """You are an expert academic book analysis assistant specializing in knowledge graph construction. Your task is to analyze book content and output structured JSON data.

Constraints:
- Output ONLY valid JSON, no other text or explanations
- Use English field names exactly as specified
- Never use placeholder text like "TBD", "N/A", "待分析"
- All content must be substantive and based on the provided text
- Arrays must never be null; use empty array [] if no data available"""


CHUNK_ANALYSIS_PROMPT = """Extract structured data from the following book content. Output ONLY valid JSON, no other text.

Book: {book_title}

Content:
{chunk_content}

Required JSON format (use EXACTLY these field names):
{{
  "chapter_summaries": ["Brief summary of each chapter found in this content"],
  "core_concepts": ["Key concept names extracted from the content"],
  "key_insights": ["Important insights or arguments from the content"],
  "key_quotes": ["Notable quotes found in the content"]
}}

Rules:
- Output ONLY the JSON object, nothing else
- Do NOT wrap in markdown code blocks (```json)
- All fields must be arrays, never null
- Use English field names exactly as shown
- If no data for a field, use empty array []
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

🔴🔴🔴 **质量铁律 - 违反即失败** 🔴🔴🔴

1. **禁止占位符**：严禁输出以下任何敷衍内容：
   - "书中未涉及此项内容"、"书中未提供"、"无法确定"
   - "待分析"、"待补充"、"TBD"、"TODO"、"N/A"
   - "此处省略"、"中间内容省略"、"示例"
   - "（完整内容未提供）"

2. **禁止空洞章节**：每个章节的 core_argument 必须有实质性内容（≥50字符）

3. **⛔ 禁止章节合并偷懒**（最严重！）：
   - 禁止用 "1-10"、"11-22" 等合并编号
   - 禁止用 "第1-10章"、"第11-22章" 等合并标题
   - 禁止合并多个章节为一个条目
   - 每个章节必须独立输出，章节数必须接近预期值

4. **数量硬指标**：
   - core_concepts: ≥3个（每个definition≥100字符）
   - key_quotes: ≥3个（必须是书中真实句子）
   - key_insights: ≥2个（每个description≥100字符）
   - chapters数量必须 ≥ 预期章节数的80%

5. **内容真实性**：
   - 金句必须是书中实际出现的原文（不可虚构）
   - 概念定义必须基于书籍内容（不可空泛）
   - 案例必须来自具体章节（不可泛泛描述）

违反以上任何规则，输出将被判定为不合格并触发重试！

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
5. **禁止章节合并**：每个 chapter_number 必须是单个数字（如"1"、"22"），禁止用"11-22"合并

正确示例：
```json
"chapters": [
  {{"chapter_number": "1", "title": "第一章", "core_argument": "...", ...}},
  {{"chapter_number": "2", "title": "第二章", "core_argument": "...", ...}},
  ...（全部章节）
]
```

错误示例（会导致解析失败）：
```json
"chapters": [
  // 此处省略，请完整复制（❌ JSON不支持注释）
  {{"chapter_number": "N/A", "title": "示例"...}} // ❌ 这是错误做法
]
```

【分析结果】
{all_chunk_analyses}

【综合要求】
请生成完整的 BookGraph JSON，包含以下部分：

1. metadata: 书籍元数据
   - title: 字符串
   - author: 字符串
   - author_intro: 字符串（作者简介，≥100字符）
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


# ═══════════════════════════════════════════════════════════════════════
# 四种摘要策略 Prompt 模板（Aquinas 项目灵感）
# ═══════════════════════════════════════════════════════════════════════

SUMMARIZATION_STRATEGIES = {
    "hierarchical": {
        "description": "按书籍原有层级结构组织摘要",
        "system_prompt": """你是一个专业的书籍分析助手。你的任务是按书籍的原有层级结构组织摘要。

【策略】Hierarchical - 层级结构摘要
- 严格按照书籍的章节/小节层级组织输出
- 保持与目录结构一致的父子关系
- 每个层级应有明确的标题标识

【输出要求】
请生成结构化的书籍分析结果，保持层级关系清晰。""",
        "user_template": """请分析以下书籍内容，按层级结构组织摘要。

【书籍信息】
书名：{book_title}
作者：{author}

【内容】
{content}

【层级结构要求】
1. 先识别书籍的整体结构（篇/章/节）
2. 按层级顺序组织内容摘要
3. 保持父子层级关系清晰
4. 每级标题需要明确标识

请生成层级结构化的分析结果。"""
    },
    "thematic": {
        "description": "按主题聚类组织摘要",
        "system_prompt": """你是一个专业的书籍分析助手。你的任务是将书籍内容按主题聚类组织摘要。

【策略】Thematic - 主题聚类摘要
- 识别书籍中的核心主题和子主题
- 将相关内容按主题归类，而不是按章节顺序
- 展示主题之间的关联关系

【输出要求】
请生成按主题聚类的书籍分析结果，展示主题网络。""",
        "user_template": """请分析以下书籍内容，按主题聚类组织摘要。

【书籍信息】
书名：{book_title}
作者：{author}

【内容】
{content}

【主题聚类要求】
1. 识别书籍中的 3-5 个核心主题
2. 每个主题下的相关内容归类在一起
3. 标注主题之间的关联关系（支持、反对、补充）
4. 展示主题网络结构

请生成主题聚类化的分析结果。"""
    },
    "adaptive": {
        "description": "自动选择最优策略",
        "system_prompt": """你是一个专业的书籍分析助手。你的任务是自动选择最优的摘要策略。

【策略】Adaptive - 自适应摘要
- 首先判断书籍的类型（学术/商业/小说/技术等）
- 根据书籍类型自动选择最合适的组织方式
- 学术类：按论点-论据结构
- 商业类：按问题-解决方案结构
- 小说类：按情节-人物-主题结构
- 技术类：按概念-原理-应用结构

【输出要求】
请先判断书籍类型，然后生成适配的分析结果。""",
        "user_template": """请分析以下书籍内容，先判断书籍类型，再选择最优策略。

【书籍信息】
书名：{book_title}
作者：{author}

【内容】
{content}

【自适应要求】
1. 首先分析内容，判断书籍类型（学术/商业/小说/技术/哲学/历史/其他）
2. 根据书籍类型选择最合适的组织方式：
   - 学术类：按论点-论据结构
   - 商业类：按问题-解决方案结构
   - 小说类：按情节-人物-主题结构
   - 技术类：按概念-原理-应用结构
   - 哲学/历史类：按思想演进-时代背景结构
3. 生成适配的分析结果

请先输出书籍类型判断，然后生成对应的分析结果。"""
    },
    "critical": {
        "description": "批判性视角，包含反对意见和局限性",
        "system_prompt": """你是一个专业的书籍分析助手。你的任务是从批判性视角分析书籍。

【策略】Critical - 批判性摘要
- 识别作者的核心论点
- 分析作者的可能假设和偏见
- 提供反对意见和局限性分析
- 与主流观点进行对比
- 质疑论证的有效性

【输出要求】
请生成包含批判性分析的结果，包括：
1. 作者的潜在假设
2. 可能的问题和局限
3. 与主流观点的矛盾或一致
4. 论证的有效性质疑""",
        "user_template": """请从批判性视角分析以下书籍。

【书籍信息】
书名：{book_title}
作者：{author}

【内容】
{content}

【批判性分析要求】
1. 识别作者的核心论点
2. 分析作者的潜在假设和偏见
3. 指出可能的问题和局限性
4. 提供反对意见（如果有）
5. 与主流观点进行对比
6. 质疑论证的有效性

请生成包含批判性分析的结果。"""
    }
}


def get_strategy_prompt(strategy: str, book_title: str, author: str, content: str) -> tuple:
    """
    获取指定策略的 prompt 模板

    Args:
        strategy: 策略名称 (hierarchical/thematic/adaptive/critical)
        book_title: 书名
        author: 作者
        content: 内容

    Returns:
        (system_prompt, user_prompt) 元组
    """
    if strategy not in SUMMARIZATION_STRATEGIES:
        logger.warning(f"Unknown strategy: {strategy}, using 'adaptive'")
        strategy = "adaptive"

    strategy_config = SUMMARIZATION_STRATEGIES[strategy]
    return (
        strategy_config["system_prompt"],
        strategy_config["user_template"].format(
            book_title=book_title,
            author=author,
            content=content
        )
    )


def detect_book_type(content: str) -> str:
    """
    根据内容自动检测书籍类型

    Args:
        content: 书籍内容样本

    Returns:
        书籍类型 (academic/business/fiction/technical/philosophy/history/other)
    """
    content_lower = content.lower()

    # 学术类特征
    academic_keywords = ["研究", "理论", "分析", "实证", "假设", "论文", "文献综述", "方法论"]
    academic_count = sum(1 for kw in academic_keywords if kw in content_lower)

    # 商业类特征
    business_keywords = ["商业模式", "战略", "市场", "客户", "产品", "增长", "盈利", "竞争优势"]
    business_count = sum(1 for kw in business_keywords if kw in content_lower)

    # 小说类特征
    fiction_keywords = ["他", "她", "说道", "心想", "走进", "房间", "突然", "于是"]
    fiction_count = sum(1 for kw in fiction_keywords if kw in content_lower)

    # 技术类特征
    tech_keywords = ["代码", "编程", "算法", "系统", "架构", "数据库", "接口", "实现"]
    tech_count = sum(1 for kw in tech_keywords if kw in content_lower)

    # 哲学类特征
    philosophy_keywords = ["思想", "哲学", "存在", "本质", "意义", "价值", "理性", "意识"]
    philosophy_count = sum(1 for kw in philosophy_keywords if kw in content_lower)

    # 历史类特征
    history_keywords = ["年", "世纪", "朝代", "战争", "帝国", "王朝", "历史", "时代"]
    history_count = sum(1 for kw in history_keywords if kw in content_lower)

    # 找出最高分
    scores = {
        "academic": academic_count,
        "business": business_count,
        "fiction": fiction_count,
        "technical": tech_count,
        "philosophy": philosophy_count,
        "history": history_count
    }

    max_type = max(scores, key=scores.get)
    max_score = scores[max_type]

    if max_score < 2:
        return "other"

    return max_type


