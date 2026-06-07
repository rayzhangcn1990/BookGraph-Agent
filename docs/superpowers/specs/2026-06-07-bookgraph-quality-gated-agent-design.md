# BookGraph 质量门控型 Agent 设计

日期：2026-06-07

## 背景

BookGraph-Agent 当前可以完成 EPUB 解析、chunk 分析、two-stage 综合和 Obsidian 写入，但真实运行《瞧，这个人》时出现了典型的 Agent 完成判定问题：

- EPUB 解析成功：72201 字符；
- chunk 分析成功：30/30；
- 预期章节数：22；
- two-stage 综合后 BookGraph 仅构造 6 章；
- 主图谱仍包含大量“待补充 / 描述待补充”；
- 系统仍输出“处理完成”并写入正式 Obsidian 文件。

这说明当前系统更像流水线执行器，而不是质量优先的目标导向 Agent。它以“文件写入成功”为完成条件，而不是以“生成完整、可用、高质量的书籍知识图谱”为完成条件。

## 目标

采用质量优先策略：宁可慢一点，也必须接近完整章节覆盖，禁止“待补充”，不合格不写正式文件。

第一阶段目标：

1. 章节覆盖不足时拒绝正式写入；
2. 出现占位符时拒绝正式写入；
3. 质量失败时保存质量报告和 checkpoint；
4. 不再把低质量结果标记为成功；
5. 不覆盖已有正式图谱。

非目标：

- 第一阶段不重构完整多 Agent 调度；
- 第一阶段不要求自动补齐所有缺失章节；
- 第一阶段不追求速度优化；
- 第一阶段不引入新的外部服务。

## Agent 角色边界

### Planner：章节计划与质量契约生成器

Planner 负责识别书籍结构、目录、章节数量，并生成后续阶段必须遵守的质量契约。

输出示例：

```json
{
  "book_title": "瞧，这个人",
  "discipline": "哲学",
  "expected_chapters": 22,
  "quality_contract": {
    "min_chapter_coverage": 0.9,
    "allow_placeholders": false,
    "required_sections": [
      "metadata",
      "time_background",
      "chapters",
      "core_concepts",
      "key_insights",
      "critical_analysis",
      "learning_path"
    ]
  }
}
```

第一阶段可以沿用现有 expected chapter 计算，不需要新增完整 Planner 类；但 expected_chapters 必须进入质量门，而不是只出现在日志里。

### Extractor：局部信息抽取器

Extractor 负责 chunk 级局部抽取。它的目标不是生成最终图谱，而是提供可靠素材。

输出应保留：

- chunk_index；
- chapter_candidates；
- core_concepts；
- key_insights；
- key_quotes；
- parse warnings；
- raw response 或失败诊断。

### Synthesizer：结构化图谱生成器

Synthesizer 基于 chunk analyses 和 BookPlan 生成 DraftBookGraph。

第一阶段仍可沿用现有 `two_stage_ingest`，但它的输出只能视为草稿，不能直接写正式文件。

### Verifier：质量门控器

Verifier 是第一阶段的核心。它负责检查：

- 章节覆盖率；
- 占位符；
- 模板化内容；
- 必填字段完整性；
- 核心概念、洞见、金句等内容密度；
- 数据流一致性。

输出示例：

```json
{
  "passed": false,
  "score": 42,
  "chapter_coverage": {
    "expected": 22,
    "actual": 6,
    "ratio": 0.27
  },
  "placeholder_count": 49,
  "blocking_issues": [
    "章节覆盖率不足：6/22",
    "发现 49 处占位符"
  ],
  "repair_hints": [
    "补齐缺失章节",
    "重写含占位符的字段"
  ]
}
```

### Repairer：失败结果修复器

Repairer 在第二阶段实现。它读取 QualityReport，只补失败部分，而不是整本重跑。

典型动作：

- 对缺失章节执行 targeted prompt；
- 对占位字段执行 targeted rewrite；
- 修复后重新进入 Verifier；
- 超过最大修复次数后失败退出。

### Writer：受质量门保护的写入器

Writer 只负责写入，不负责决定任务是否成功。

规则：

```text
QualityReport passed  → 写正式 .md / .insights.md / summary
QualityReport failed  → 不覆盖正式 .md，写 failed report / checkpoint / 可选 draft
```

## 数据流

新数据流：

```text
BookInput
→ BookPlan
→ ChunkEvidence[]
→ DraftBookGraph
→ QualityReport
→ WriteDecision
```

第一阶段的实际落地数据流：

```text
process_single_book_optimized()
  parse EPUB/PDF/MOBI
  split chunks
  process chunks
  synthesize DraftBookGraph
  construct BookGraph
  convert BookGraph to dict
  run BookGraphQualityChecker(expected_chapters)
  if failed:
      save failed report
      optionally save draft
      do not call writer.write_book_graph()
      return failed status
  else:
      generate markdown
      writer.write_book_graph()
      generate insights / summaries
      return success
```

## 失败处理

### 外部执行失败

包括 provider 502、空响应、timeout、rate limit。

处理方式：

1. 当前 chunk 或当前阶段 retry；
2. 超过次数后保存 checkpoint；
3. 返回 external failure；
4. 不写正式文件。

### JSON / schema 失败

包括 JSON 解析失败、字段名不匹配、数组变字符串。

处理方式：

1. parse repair；
2. schema normalize；
3. 仍失败则 retry 当前调用；
4. 保存 raw response；
5. 不得用“待补充”补字段伪装通过。

### 质量失败

包括章节覆盖不足、占位符污染、模板化内容、必填字段缺失。

第一阶段处理方式：

1. 拒绝正式写入；
2. 保存 failed report；
3. 返回 failed；
4. 日志明确说明失败原因。

第二阶段处理方式：

1. 进入 Repairer；
2. 根据 QualityReport 补缺失章节或字段；
3. 重新验证；
4. 仍失败则拒绝正式写入。

## 写入策略

正式文件写入是发布动作，必须受质量门保护。

建议目录：

```text
cache/checkpoints/<book>_quality_failed.json
cache/checkpoints/<book>_draft.json
cache/checkpoints/<book>_raw_response.json
```

可选 draft 输出：

```text
<book>.draft.md
```

第一阶段推荐先保存 JSON 质量报告，避免污染 Obsidian Vault。

## 测试与验收

新增测试文件：

```text
tests/test_quality_gate.py
```

必须覆盖：

1. `test_rejects_low_chapter_coverage`
   - expected_chapters=22；
   - actual chapters=6；
   - 期望质量失败；
   - writer 不被调用。

2. `test_rejects_placeholder_pollution`
   - 输入包含“待补充 / 描述待补充 / TODO / N/A”；
   - 期望质量失败；
   - writer 不被调用。

3. `test_allows_high_quality_graph`
   - 章节覆盖率 >= 90%；
   - 无占位符；
   - 期望正式写入。

4. `test_failed_quality_does_not_overwrite_existing_file`
   - 已有正式文件；
   - 新结果质量失败；
   - 期望旧文件内容不变。

5. `test_failed_quality_writes_report`
   - 质量失败后生成质量报告；
   - 报告包含 expected、actual、score、blocking issues。

真实运行验收：

```bash
python main.py \
  --input "/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/瞧，这个人.epub" \
  --discipline 哲学 \
  --parallel 1
```

如果仍出现：

```text
expected_chapters = 22
actual_chapters = 6
placeholder_count > 0
```

期望日志为：

```text
❌ 质量检查失败
章节覆盖率不足：6/22
占位符污染：49 处
未写入正式文件
质量报告已保存：...
```

禁止出现：

```text
✅ 处理完成
```

## 分阶段落地计划

### 第一阶段：硬质量门

- 将 expected_chapters 传入 BookGraphQualityChecker；
- 在正式写入前运行质量检查；
- 章节覆盖不足或占位符污染时拒绝写入；
- 保存质量失败报告；
- 返回失败状态。

### 第二阶段：自动 Repairer

- 根据质量报告修复缺失章节和占位字段；
- 最多 N 次修复；
- 修复后重新验证；
- 仍失败则拒绝写入。

### 第三阶段：章节计划驱动管线

- Planner 生成完整章节计划；
- ChapterSynthesizer 逐章生成；
- 每章独立质量校验；
- GlobalSynthesizer 基于合格章节生成全书级概念、洞见、案例和批判分析；
- Writer 只写完整通过的结果。

## 风险与约束

- 第一阶段会让系统更频繁地返回失败，这是预期行为；它暴露了真实质量问题。
- 如果已有旧文件质量较差，第一阶段不会自动清理旧文件，只会避免新失败结果覆盖。
- 质量门阈值需要平衡，章节覆盖率建议默认 90%，但可以配置。
- 禁止用占位符补字段会让部分 schema 构造失败；这是正确失败，不应绕过。

## 决策

采用质量优先策略，按三阶段落地：

1. 先实现硬质量门，解决伪成功；
2. 再实现自动 repair，减少人工重跑；
3. 最终演进为章节计划驱动的多角色 Agent 管线。
