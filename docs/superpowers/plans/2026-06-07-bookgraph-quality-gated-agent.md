# BookGraph Quality-Gated Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage quality gate for BookGraph-Agent so low-quality generated graphs fail honestly, do not overwrite formal Obsidian files, and produce a machine-readable quality report.

**Architecture:** Keep the existing parse → chunk → synthesize → BookGraph flow, but insert a Verifier gate before any formal write. The gate converts the draft BookGraph to a dict, runs `BookGraphQualityChecker` with `expected_chapters`, saves a failed-quality report on failure, and only allows `ObsidianWriter.write_book_graph()` when quality passes.

**Tech Stack:** Python 3, Pydantic v2 `BookGraph`, existing `BookGraphQualityChecker`, pytest, pathlib/json, existing CLI `main.py`.

---

## File Structure

### Create

- `core/quality_gate.py`
  - Responsibility: Convert draft BookGraph/dict into a quality decision, save failure reports, and keep writer logic out of quality logic.
  - Public API:
    - `QualityGateDecision`
    - `book_graph_to_dict(book_graph)`
    - `evaluate_book_graph_quality(book_graph, expected_chapters, report_dir, book_title)`

- `tests/test_quality_gate.py`
  - Responsibility: Unit-test the Verifier gate independently from LLM calls and Obsidian writing.

### Modify

- `main.py`
  - Insert quality gate between BookGraph construction and Markdown generation.
  - On failed quality, return `success: False`, include `quality_report_path`, and do not call writer.

### No first-stage changes

- `core/llm_client.py`
  - Do not remove fallback normalization in this first stage. The new gate will reject fallback-generated placeholders before formal writing.

- `core/two_stage_ingest.py`
  - Do not refactor synthesis in this first stage. Later phases will add repair and chapter-plan synthesis.

- `core/book_graph_quality_checker.py`
  - Reuse existing checks. Do not change thresholds in this first stage unless tests expose a mismatch.

---

## Task 1: Add Quality Gate Module

**Files:**
- Create: `core/quality_gate.py`
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Write failing tests for quality-gate decisions**

Create `tests/test_quality_gate.py` with this content:

```python
"""质量门控测试：低质量 BookGraph 不得写入正式文件。"""

import json
from pathlib import Path

from core.quality_gate import evaluate_book_graph_quality


def _chapter(num: int) -> dict:
    return {
        "chapter_number": str(num),
        "title": f"第{num}章",
        "core_argument": "本章围绕尼采的自我理解展开，说明哲学思想与生命经验之间的张力。",
        "underlying_logic": "前提假设：哲学文本植根生命经验→推理链条：自我叙述呈现价值判断→核心结论：自传是哲学实践的一部分",
        "related_books": [],
        "critical_questions": ["这种自我叙述是否会遮蔽历史事实？"],
    }


def _valid_graph(chapter_count: int = 10) -> dict:
    return {
        "metadata": {
            "title": "测试书籍",
            "author": "测试作者",
            "author_intro": "测试作者是一位思想史研究者，作品集中讨论现代主体性与价值重估。",
            "discipline": "哲学",
            "tags": ["哲学"],
            "category": [],
            "related_books": [],
        },
        "time_background": {
            "macro_background": "十九世纪欧洲思想界经历宗教权威衰落、科学理性扩张与价值危机。",
            "micro_background": "作者在个人健康、学术孤立和创作高峰之间形成强烈的自我解释需求。",
            "core_contradiction": "思想上的高度自信与现实中的孤立处境构成全书核心张力。",
        },
        "chapters": [_chapter(i) for i in range(1, chapter_count + 1)],
        "core_concepts": [
            {
                "name": f"核心概念{i}",
                "definition": "这是一个具有明确哲学含义的概念，用于解释文本中的价值判断。",
                "deep_meaning": "该概念揭示了作者如何将个人经验转化为普遍性的思想命题。",
                "underlying_logic": "前提假设：概念来自文本问题→推理链条：问题推动概念形成→核心结论：概念服务于整体论证",
                "development_stages": [],
                "core_drivers": ["价值危机"],
                "critical_review": "该概念具有解释力，但也可能过度强调主体经验。",
                "related_books": [],
            }
            for i in range(1, 6)
        ],
        "key_insights": [
            {
                "title": f"关键洞见{i}",
                "description": "这一洞见说明文本并非普通自传，而是对哲学立场的回顾与辩护。",
                "underlying_logic": "前提假设：自传可以承载哲学论证→推理链条：生命叙事组织思想材料→核心结论：文本具有元哲学性质",
                "deep_assumptions": ["生命经验可作为哲学证据"],
                "controversies": "争议在于自我解释是否会放大作者的主体神话。",
                "multi_perspectives": {"思想史": "可作为现代主体性危机的案例"},
            }
            for i in range(1, 6)
        ],
        "key_cases": [
            {
                "name": f"关键案例{i}",
                "source_chapter": "1",
                "event_description": "该案例展示作者如何把生命事件转化为哲学判断。",
                "development_stages": [],
                "core_drivers": ["自我解释"],
                "historical_limitations": "案例解释依赖作者视角，可能缺少外部证据。",
            }
            for i in range(1, 4)
        ],
        "key_quotes": [
            {
                "text": f"这是一条用于测试的关键引文{i}，长度足够通过基础质量检查。",
                "chapter": "1",
                "core_theme": "自我理解",
                "background_context": "文本讨论作者如何理解自身思想使命。",
                "underlying_logic": "前提假设：引文浓缩论点→推理链条：引文连接章节主题→核心结论：引文可作为图谱节点",
            }
            for i in range(1, 4)
        ],
        "critical_analysis": {
            "feminist_perspective": "从性别视角看，文本中的主体叙事仍以男性哲学家的自我塑造为中心。",
            "postcolonial_perspective": "从后殖民视角看，文本主要体现欧洲思想内部的价值危机。",
        },
        "learning_path": {
            "beginner": ["先了解作者生平与十九世纪思想背景"],
            "advanced": ["比较本书与作者其他成熟期作品"],
            "research": ["研究自传体哲学写作的思想史意义"],
            "practice": ["将概念关系整理为 Obsidian 双链笔记"],
        },
        "book_network": {"related_books": []},
    }


def test_rejects_low_chapter_coverage(tmp_path: Path):
    graph = _valid_graph(chapter_count=6)

    decision = evaluate_book_graph_quality(
        graph,
        expected_chapters=22,
        report_dir=tmp_path,
        book_title="测试书籍",
    )

    assert decision.passed is False
    assert decision.formal_write_allowed is False
    assert decision.report_path is not None
    assert decision.report_path.exists()
    assert any("章节覆盖率" in issue for issue in decision.issues)

    report = json.loads(decision.report_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["stats"]["expected_chapters"] == 22
    assert report["stats"]["chapter_count"] == 6


def test_rejects_placeholder_pollution(tmp_path: Path):
    graph = _valid_graph(chapter_count=10)
    graph["key_insights"][0]["description"] = "描述待补充"

    decision = evaluate_book_graph_quality(
        graph,
        expected_chapters=10,
        report_dir=tmp_path,
        book_title="测试书籍",
    )

    assert decision.passed is False
    assert decision.formal_write_allowed is False
    assert decision.report_path is not None
    assert any("占位符" in issue for issue in decision.issues)


def test_allows_high_quality_graph(tmp_path: Path):
    graph = _valid_graph(chapter_count=10)

    decision = evaluate_book_graph_quality(
        graph,
        expected_chapters=10,
        report_dir=tmp_path,
        book_title="测试书籍",
    )

    assert decision.passed is True
    assert decision.formal_write_allowed is True
    assert decision.report_path is None
    assert decision.score >= 70
```

- [ ] **Step 2: Run tests to verify they fail because module does not exist**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
ModuleNotFoundError: No module named 'core.quality_gate'
```

- [ ] **Step 3: Implement the quality gate module**

Create `core/quality_gate.py` with this content:

```python
"""BookGraph 质量门控。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.book_graph_quality_checker import BookGraphQualityChecker


@dataclass(frozen=True)
class QualityGateDecision:
    """质量门控决策。"""

    passed: bool
    formal_write_allowed: bool
    score: float
    issues: List[str]
    warnings: List[str]
    stats: Dict[str, Any]
    report_path: Optional[Path] = None


def book_graph_to_dict(book_graph: Any) -> Dict[str, Any]:
    """将 BookGraph 或 dict 转成质量检查器可消费的 dict。"""
    if isinstance(book_graph, dict):
        return book_graph
    if hasattr(book_graph, "model_dump"):
        return book_graph.model_dump(mode="json")
    if hasattr(book_graph, "dict"):
        return book_graph.dict()
    raise TypeError(f"不支持的 BookGraph 类型：{type(book_graph).__name__}")


def evaluate_book_graph_quality(
    book_graph: Any,
    expected_chapters: int,
    report_dir: Path,
    book_title: str,
) -> QualityGateDecision:
    """检查 BookGraph 质量，失败时保存机器可读报告。"""
    graph_data = book_graph_to_dict(book_graph)
    checker = BookGraphQualityChecker()
    result = checker.check(graph_data, expected_chapters)

    if result.passed:
        return QualityGateDecision(
            passed=True,
            formal_write_allowed=True,
            score=result.score,
            issues=result.issues,
            warnings=result.warnings,
            stats=result.stats,
            report_path=None,
        )

    report_path = save_quality_failure_report(
        report_dir=report_dir,
        book_title=book_title,
        score=result.score,
        issues=result.issues,
        warnings=result.warnings,
        stats=result.stats,
    )

    return QualityGateDecision(
        passed=False,
        formal_write_allowed=False,
        score=result.score,
        issues=result.issues,
        warnings=result.warnings,
        stats=result.stats,
        report_path=report_path,
    )


def save_quality_failure_report(
    report_dir: Path,
    book_title: str,
    score: float,
    issues: List[str],
    warnings: List[str],
    stats: Dict[str, Any],
) -> Path:
    """保存质量失败报告。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _safe_filename(book_title)
    report_path = report_dir / f"{safe_title}_quality_failed.json"
    report = {
        "book_title": book_title,
        "passed": False,
        "score": score,
        "issues": issues,
        "warnings": warnings,
        "stats": stats,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return report_path


def _safe_filename(value: str) -> str:
    """生成适合作为检查点文件名的标题。"""
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "untitled"
```

- [ ] **Step 4: Run quality gate tests**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
3 passed
```

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add core/quality_gate.py tests/test_quality_gate.py
git commit -m "feat: add BookGraph quality gate"
```

---

## Task 2: Protect Main Flow Formal Writes

**Files:**
- Modify: `main.py`
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Add a failing integration-style test for rejecting formal writes**

Append this test to `tests/test_quality_gate.py`:

```python
from unittest.mock import Mock, patch

import pytest


@pytest.mark.asyncio
async def test_process_rejects_low_quality_before_writer(tmp_path: Path):
    from main import process_single_book_optimized

    parse_result = Mock()
    parse_result.success = True
    parse_result.error = None
    parse_result.content = "测试内容" * 100
    parse_result.metadata = {"title": "测试书籍", "author": "测试作者"}
    parse_result.chapters = [
        {"title": f"第{i}章", "content": "测试章节内容" * 20}
        for i in range(1, 23)
    ]

    low_quality_synthesis = _valid_graph(chapter_count=6)

    with patch("main.BookParser") as parser_cls, \
        patch("main.get_llm_client") as get_client, \
        patch("main.process_book_chunks_optimized") as process_chunks, \
        patch("core.two_stage_ingest.TwoStageIngest.process") as two_stage_process, \
        patch("main.ObsidianWriter") as writer_cls:

        parser_cls.return_value.parse.return_value = parse_result
        get_client.return_value = Mock()
        process_chunks.return_value = [{"chapter_summaries": []}]
        two_stage_process.return_value = low_quality_synthesis

        result = await process_single_book_optimized(
            book_path=tmp_path / "book.epub",
            config={
                "improvements": {"two_stage_ingest": {"enabled": True}},
                "quality_gate": {"report_dir": str(tmp_path / "quality_reports")},
                "obsidian": {"vault_path": str(tmp_path / "vault")},
            },
            discipline="哲学",
            max_parallel=1,
        )

        assert result["success"] is False
        assert result["failure_type"] == "quality_gate"
        assert "quality_report_path" in result
        assert Path(result["quality_report_path"]).exists()
        writer_cls.return_value.write_book_graph.assert_not_called()
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
pytest tests/test_quality_gate.py::test_process_rejects_low_quality_before_writer -v
```

Expected result before implementation:

```text
AssertionError: expected write_book_graph to not have been called
```

or:

```text
KeyError: 'failure_type'
```

- [ ] **Step 3: Modify `main.py` imports inside quality gate location**

In `main.py`, at the current location after BookGraph construction and before this line:

```python
# Step 5: 写入 Obsidian
```

insert this block:

```python
        # Step 5: 质量门控（正式写入前）
        from core.quality_gate import evaluate_book_graph_quality

        quality_config = config.get('quality_gate', {})
        report_dir = Path(
            quality_config.get('report_dir', 'cache/checkpoints/quality_reports')
        )
        quality_decision = evaluate_book_graph_quality(
            book_graph,
            expected_chapters=expected_chapters,
            report_dir=report_dir,
            book_title=book_title,
        )

        if not quality_decision.formal_write_allowed:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error("   ❌ 质量检查失败，未写入正式文件")
            for issue in quality_decision.issues[:8]:
                logger.error(f"      - {issue}")
            if quality_decision.report_path:
                logger.error(f"   📄 质量报告已保存: {quality_decision.report_path}")
            return {
                'success': False,
                'failure_type': 'quality_gate',
                'quality_score': quality_decision.score,
                'quality_issues': quality_decision.issues,
                'quality_warnings': quality_decision.warnings,
                'quality_stats': quality_decision.stats,
                'quality_report_path': str(quality_decision.report_path) if quality_decision.report_path else None,
                'chunks_processed': len(chunk_results),
                'elapsed_seconds': elapsed,
            }
```

Then change the existing comment immediately below from:

```python
        # Step 5: 写入 Obsidian
```

to:

```python
        # Step 6: 写入 Obsidian（仅质量通过后）
```

- [ ] **Step 4: Run the protected-write test**

Run:

```bash
pytest tests/test_quality_gate.py::test_process_rejects_low_quality_before_writer -v
```

Expected result:

```text
1 passed
```

- [ ] **Step 5: Run all quality gate tests**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
4 passed
```

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add main.py tests/test_quality_gate.py
git commit -m "feat: block formal writes on quality failure"
```

---

## Task 3: Add Existing-File Protection Regression

**Files:**
- Modify: `tests/test_quality_gate.py`

- [ ] **Step 1: Add regression test showing failed quality does not overwrite existing file**

Append this test to `tests/test_quality_gate.py`:

```python
@pytest.mark.asyncio
async def test_failed_quality_does_not_overwrite_existing_file(tmp_path: Path):
    from main import process_single_book_optimized

    vault_book_dir = tmp_path / "vault" / "📚 知识图谱" / "哲学" / "书籍图谱"
    vault_book_dir.mkdir(parents=True)
    existing_file = vault_book_dir / "测试书籍.md"
    existing_file.write_text("已有高质量正式文件", encoding="utf-8")

    parse_result = Mock()
    parse_result.success = True
    parse_result.error = None
    parse_result.content = "测试内容" * 100
    parse_result.metadata = {"title": "测试书籍", "author": "测试作者"}
    parse_result.chapters = [
        {"title": f"第{i}章", "content": "测试章节内容" * 20}
        for i in range(1, 23)
    ]

    low_quality_synthesis = _valid_graph(chapter_count=6)

    with patch("main.BookParser") as parser_cls, \
        patch("main.get_llm_client") as get_client, \
        patch("main.process_book_chunks_optimized") as process_chunks, \
        patch("core.two_stage_ingest.TwoStageIngest.process") as two_stage_process:

        parser_cls.return_value.parse.return_value = parse_result
        get_client.return_value = Mock()
        process_chunks.return_value = [{"chapter_summaries": []}]
        two_stage_process.return_value = low_quality_synthesis

        result = await process_single_book_optimized(
            book_path=tmp_path / "book.epub",
            config={
                "improvements": {"two_stage_ingest": {"enabled": True}},
                "quality_gate": {"report_dir": str(tmp_path / "quality_reports")},
                "obsidian": {
                    "vault_path": str(tmp_path / "vault"),
                    "discipline_paths": {"哲学": "📚 知识图谱/哲学"},
                    "subdirectories": {"books": "书籍图谱"},
                },
            },
            discipline="哲学",
            max_parallel=1,
        )

    assert result["success"] is False
    assert existing_file.read_text(encoding="utf-8") == "已有高质量正式文件"
```

- [ ] **Step 2: Run the regression test**

Run:

```bash
pytest tests/test_quality_gate.py::test_failed_quality_does_not_overwrite_existing_file -v
```

Expected result:

```text
1 passed
```

- [ ] **Step 3: Run all quality gate tests**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
5 passed
```

- [ ] **Step 4: Commit Task 3**

Run:

```bash
git add tests/test_quality_gate.py
git commit -m "test: verify failed quality preserves existing output"
```

---

## Task 4: Add Speed Diagnostics Without Changing Scheduling

**Files:**
- Modify: `main.py`
- Test: `tests/test_quality_gate.py`

- [ ] **Step 1: Add assertions for elapsed timing fields in quality failure result**

In `test_process_rejects_low_quality_before_writer`, add these assertions near the existing result assertions:

```python
        assert result["chunks_processed"] == 1
        assert result["elapsed_seconds"] >= 0
```

- [ ] **Step 2: Verify assertions pass**

Run:

```bash
pytest tests/test_quality_gate.py::test_process_rejects_low_quality_before_writer -v
```

Expected result:

```text
1 passed
```

- [ ] **Step 3: Add stage timing logs around quality gate**

In `main.py`, immediately before calling `evaluate_book_graph_quality`, add:

```python
        quality_start = datetime.now()
```

Immediately after the call, add:

```python
        quality_elapsed = (datetime.now() - quality_start).total_seconds()
        logger.info(
            f"   🧪 质量门检查完成: score={quality_decision.score:.0f}, "
            f"passed={quality_decision.passed}, elapsed={quality_elapsed:.2f}秒"
        )
```

- [ ] **Step 4: Run quality tests**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
5 passed
```

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add main.py tests/test_quality_gate.py
git commit -m "chore: log quality gate timing"
```

---

## Task 5: Run Focused Existing Tests

**Files:**
- No source modifications expected.

- [ ] **Step 1: Run quality gate tests**

Run:

```bash
pytest tests/test_quality_gate.py -v
```

Expected result:

```text
5 passed
```

- [ ] **Step 2: Run JSON parsing tests because quality gate depends on normalized model output**

Run:

```bash
pytest tests/test_json_parsing_enhanced.py -v
```

Expected result:

```text
all tests pass
```

If tests fail, record exact failures and do not modify unrelated JSON parsing behavior in this plan. Create a follow-up issue or separate plan for JSON parser fixes.

- [ ] **Step 3: Run rollback checkpoint tests because failure reporting uses checkpoint-style files**

Run:

```bash
pytest tests/test_rollback_checkpoint.py -v
```

Expected result:

```text
all tests pass
```

If tests fail due to pre-existing constructor mismatches or unrelated two-stage changes, record exact failures in the final report and keep the quality-gate changes isolated.

---

## Task 6: Real Book Regression Smoke

**Files:**
- No source modifications expected unless a test exposes a quality-gate integration bug.

- [ ] **Step 1: Preserve the current formal output path for comparison**

Run:

```bash
python - <<'PY'
from pathlib import Path
p = Path('/Users/rayzhang/Documents/知识体系/📚 知识图谱/哲学/书籍图谱/瞧，这个人（德国哲学家尼采的自传，德文原版全新译本，“那些无法杀死你的，必将使你强大”）.md')
print(p.exists())
if p.exists():
    print(p.stat().st_size)
    print(p.read_text(encoding='utf-8')[:80])
PY
```

Expected result:

```text
True
<size number>
<first 80 characters>
```

- [ ] **Step 2: Run the real EPUB command**

Run:

```bash
python main.py \
  --input "/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/瞧，这个人.epub" \
  --discipline 哲学 \
  --parallel 1
```

Expected result if synthesis still returns 6/22 with placeholders:

```text
❌ 质量检查失败，未写入正式文件
章节覆盖率不足...
占位符污染...
质量报告已保存...
```

Expected result if synthesis produces high-quality output:

```text
质量门检查完成: passed=True
✅ 处理完成: <formal output path>
```

- [ ] **Step 3: Confirm failed quality did not overwrite formal output**

Only if Step 2 returns `failure_type=quality_gate` or logs quality failure, run:

```bash
python - <<'PY'
from pathlib import Path
p = Path('/Users/rayzhang/Documents/知识体系/📚 知识图谱/哲学/书籍图谱/瞧，这个人（德国哲学家尼采的自传，德文原版全新译本，“那些无法杀死你的，必将使你强大”）.md')
print(p.exists())
if p.exists():
    text = p.read_text(encoding='utf-8')
    print(p.stat().st_size)
    print(text.count('待补充'))
PY
```

Expected result:

```text
The file still exists if it existed before, and its content was not replaced by a new failed-quality graph.
```

- [ ] **Step 4: Inspect the quality report**

Run:

```bash
python - <<'PY'
from pathlib import Path
reports = sorted(Path('cache/checkpoints/quality_reports').glob('*quality_failed.json'), key=lambda p: p.stat().st_mtime, reverse=True)
print(reports[0] if reports else 'NO_REPORT')
if reports:
    print(reports[0].read_text(encoding='utf-8')[:1200])
PY
```

Expected result after quality failure:

```text
A JSON report containing passed=false, score, issues, warnings, stats, expected_chapters, chapter_count, placeholder_count.
```

---

## Task 7: Document Follow-Up Speed Optimization Path

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-bookgraph-quality-gated-agent-design.md`

- [ ] **Step 1: Add speed follow-up section to the approved spec**

Append this section to `docs/superpowers/specs/2026-06-07-bookgraph-quality-gated-agent-design.md`:

```markdown

## 后续速度优化路径

第一阶段不直接提高并发，因为质量失败时提高并发只会更快地产生坏结果。速度优化应在质量门之后按以下顺序推进：

1. **减少无效写入**：质量门阻止低质正式输出，避免人工发现问题后整本重跑。
2. **局部 Repairer**：质量报告指出缺失章节和占位字段后，只补失败单元，减少整本重跑。
3. **章节级缓存**：每章独立缓存合格结果，后续只重跑失败章节。
4. **模型分层调度**：Extractor 使用便宜稳定模型，Synthesizer 和 Repairer 使用更稳定的高质量模型。
5. **动态并发**：仅对独立 chunk/章节提高并发；综合、写入、质量门保持串行。
6. **失败类型分流**：provider 502 使用 retry/backoff；质量失败使用 repair；schema 失败使用 parse repair。
```

- [ ] **Step 2: Commit Task 7**

Run:

```bash
git add docs/superpowers/specs/2026-06-07-bookgraph-quality-gated-agent-design.md
git commit -m "docs: add BookGraph speed optimization path"
```

---

## Task 8: Final Verification and Report

**Files:**
- No source modifications expected.

- [ ] **Step 1: Run focused verification suite**

Run:

```bash
pytest tests/test_quality_gate.py tests/test_json_parsing_enhanced.py tests/test_rollback_checkpoint.py -v
```

Expected result:

```text
All tests pass, or unrelated pre-existing failures are documented with exact failure names.
```

- [ ] **Step 2: Show git diff summary**

Run:

```bash
git diff --stat
```

Expected result includes only planned files:

```text
core/quality_gate.py
tests/test_quality_gate.py
main.py
docs/superpowers/specs/2026-06-07-bookgraph-quality-gated-agent-design.md
```

- [ ] **Step 3: Summarize outcomes**

Final report must include:

```text
- 是否实现质量门
- 质量失败时是否阻止正式写入
- 质量报告保存路径
- 测试命令和结果
- 真实 EPUB smoke 的结果
- 仍未解决的后续项：Repairer、章节计划驱动、模型分层调度
```

---

## Self-Review

### Spec coverage

- Hard quality gate: Task 1 and Task 2.
- Chapter coverage rejection: Task 1 tests and `BookGraphQualityChecker` integration.
- Placeholder rejection: Task 1 tests and existing checker integration.
- Failed report: Task 1 implementation and Task 6 inspection.
- Formal write protection: Task 2 and Task 3.
- Speed optimization path: Task 4 diagnostics and Task 7 follow-up documentation.
- Real EPUB validation: Task 6.

### Placeholder scan

This plan contains the word `TODO` only inside examples of forbidden model placeholders. It contains no plan placeholder requiring later filling.

### Type consistency

- `QualityGateDecision` fields are used consistently across tests and main flow.
- `evaluate_book_graph_quality()` accepts `Path` for `report_dir` and returns `QualityGateDecision`.
- `book_graph_to_dict()` supports both Pydantic v2 `model_dump()` and dict input.
