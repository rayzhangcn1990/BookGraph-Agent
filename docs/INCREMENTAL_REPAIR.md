# 📋 增量修复机制实现说明

## 核心功能

实现了"质量不达标先落盘再增量修复"机制，解决批量处理时部分质量不合格导致全量重来的问题。

## 关键变更

### 1. `core/incremental_repair.py`（新增）

**功能**：
- 保存部分合格结果（质量不达标时仍落盘）
- 自动生成修复清单（JSON + Markdown）
- 分析质量问题，生成修复项列表

**核心类**：
- `FixItem`: 单个修复项（字段路径、问题类型、建议操作等）
- `RepairManifest`: 修复清单（书籍信息 + 修复项列表）
- `IncrementalRepairSystem`: 增量修复系统主类

**修复清单示例**：
```json
{
  "book_title": "善恶的彼岸",
  "generated_at": "2026-06-19T...",
  "quality_score": 0,
  "total_issues": 10,
  "fix_items": [
    {
      "field_path": "chapters[chapter_number='11-22']",
      "issue_type": "章节合并",
      "issue_description": "章节编号 '11-22' 为合并编号，LLM偷懒行为",
      "suggested_action": "拆分为独立章节，逐章分析",
      "priority": "CRITICAL"
    },
    ...
  ]
}
```

### 2. `main.py` 修改

**变更**：
- 移除 `QualityGateError` 异常抛出
- 质量不达标时：
  1. 保存质量报告
  2. 仍然写入结果文件
  3. 生成修复清单
  4. 在输出文件添加修复标记

**新增逻辑**（Step 5）：
```python
# 质量不达标：先落盘 + 生成修复清单（而非直接抛异常）
if not quality_passed:
    quality_path = _quality_report_path(book_title)
    quality_path.write_text(quality_report, encoding="utf-8")

    logger.warning("   ⚠️ 质量检查不通过，但会先生成结果文件，后期增量修复")
    logger.warning("   📋 质量报告: %s", quality_path)

    # Step 6 后生成修复清单
    repair_system = get_repair_system(output_path.parent)
    _, manifest_json, manifest_md = repair_system.save_partial_result(
        quality_data, quality_report, quality_stats, output_path
    )
```

### 3. `batch_repair.py`（新增）

**功能**：
- 批量扫描修复清单目录
- 按优先级定向修复（CRITICAL → HIGH → MEDIUM）
- 支持多种修复策略：
  - 章节合并：拆分为独立章节
  - 章节占位符：重新生成章节内容
  - 概念占位符：补充概念定义
  - 金句不足：提取更多金句
  - 底层逻辑格式错误：重写为标准格式

**使用方式**：
```bash
# 批量修复所有待修复书籍
python batch_repair.py --manifest-dir ".repair_manifests/"

# 单本书修复（需先生成清单）
python main.py --input "book.epub"  # 生成修复清单
python batch_repair.py --manifest-dir ".repair_manifests/"  # 批量修复
```

### 4. `config.yaml` 新增配置

```yaml
quality_gate:
  enabled: true
  threshold: 80.0
  auto_retry: true
  max_retries: 3
  lazy_write: true             # 🔑 质量不达标时仍落盘
  generate_repair_manifest: true  # 🔑 自动生成修复清单
```

## 修复清单输出示例

**Markdown 格式**（人类可读）：
```markdown
# 📋 修复清单：善恶的彼岸

**生成时间**：2026-06-19T...
**质量评分**：0/100
**问题总数**：10

---

## 🚨 需修复项（按优先级排序）

### 🔴 CRITICAL（必须修复）

#### 1. 章节合并

- **字段路径**：`chapters[chapter_number='11-22']`
- **问题描述**：章节编号 '11-22' 为合并编号，LLM偷懒行为
- **当前值**：`第11-22章：...`
- **建议操作**：拆分为独立章节，逐章分析

...
```

## 工作流程

### 批量处理流程（优化后）

```
书籍输入
  ↓
解析 + Chunk分析 + 综合生成
  ↓
质量检查
  ├─ 通过 → 写入结果文件
  └─ 不通过 → 写入结果文件 + 生成修复清单
              ↓
          后期增量修复（按清单定向修复）
```

### 增量修复流程

```
扫描修复清单目录
  ↓
加载待修复书籍列表
  ↓
逐本书籍定向修复
  ├─ CRITICAL问题 → 优先修复
  ├─ HIGH问题 → 次级修复
  └─ MEDIUM问题 → 最后修复
  ↓
重新质量检查
  ├─ 通过 → 移除修复标记
  └─ 不通过 → 更新修复清单
```

## 修复策略

| 问题类型 | 修复策略 | 优先级 |
|---------|---------|--------|
| 章节合并 | 拆分为独立章节，重新生成 | CRITICAL |
| 章节占位符 | 重新生成章节内容 | CRITICAL |
| 概念占位符 | 补充概念定义和深层含义 | HIGH |
| 浅薄概念 | 扩展概念定义 | MEDIUM |
| 金句不足 | 从原文提取更多金句 | MEDIUM |
| 底层逻辑格式错误 | 重写为标准格式 | MEDIUM |
| 占位符污染严重 | 全局清理占位符 | CRITICAL |

## 优势

1. **避免全量重来**：质量不达标时仍落盘，只修复问题部分
2. **增量修复**：按修复清单定向修复，不重新生成整本书
3. **优先级驱动**：CRITICAL问题优先修复，合理分配资源
4. **人类可读清单**：Markdown格式修复清单，方便人工审核
5. **自动化修复**：`batch_repair.py` 支持批量自动修复

## 使用建议

1. **批量处理**：运行 `python main.py --input /path/to/books/ --batch`
2. **检查修复清单**：查看 `.repair_manifests/` 目录下的 Markdown 清单
3. **人工审核**：对于 CRITICAL 问题，建议人工审核后再自动修复
4. **批量修复**：运行 `python batch_repair.py --manifest-dir .repair_manifests/`
5. **验证结果**：修复后重新检查质量报告

## 注意事项

- 修复清单保存在 Obsidian vault 的 `.repair_manifests/` 目录
- 修复标记会添加到原始 Markdown 文件的头部（Obsidian Callout 语法）
- 自动修复会消耗 LLM API 额度，建议先人工审核清单
- 部分问题（如章节合并）修复难度较高，可能需要多次尝试

---

生成时间：2026-06-19
实现者：Claude Code
