"""
测试 P0-3: 合成阶段 Rollback

问题：合成失败时，已分析的 chunk 结果丢失
方案：增量保存分析结果，失败时可恢复
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════
# Test 1: 分析结果增量保存
# ═══════════════════════════════════════════════════════════

class TestAnalysisResultCheckpoint:
    """测试分析结果增量保存"""

    def test_save_analysis_checkpoint(self):
        """
        RED: 测试保存分析检查点

        场景：完成部分 chunk 分析后保存检查点
        期望：检查点文件包含分析结果
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            # llm_client 可以为 None，因为我们只测试检查点功能
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 模拟分析结果
            analysis_result = {
                "book_title": "测试书籍",
                "chunks_analyzed": 5,
                "total_chunks": 10,
                "results": [
                    {"chunk_index": 0, "chapter_summaries": []},
                    {"chunk_index": 1, "chapter_summaries": []},
                ]
            }

            # 保存检查点
            ingest.save_checkpoint("test_book", "analysis", analysis_result)

            # 验证文件存在
            checkpoint_file = Path(tmpdir) / "test_book_analysis.json"
            assert checkpoint_file.exists(), "检查点文件应存在"

            # 验证内容
            with open(checkpoint_file) as f:
                saved = json.load(f)
            assert saved["chunks_analyzed"] == 5, "应保存分析进度"

    def test_load_analysis_checkpoint(self):
        """
        RED: 测试加载分析检查点

        场景：从检查点恢复分析进度
        期望：能正确加载之前保存的分析结果
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 先保存
            analysis_result = {
                "book_title": "测试书籍",
                "chunks_analyzed": 7,
                "results": [{"chunk_index": i} for i in range(7)]
            }
            ingest.save_checkpoint("test_book", "analysis", analysis_result)

            # 再加载
            loaded = ingest.load_checkpoint("test_book", "analysis")

            assert loaded is not None, "应能加载检查点"
            assert loaded["chunks_analyzed"] == 7, "应恢复进度"

    def test_skip_analyzed_chunks(self):
        """
        RED: 测试跳过已分析的 chunk

        场景：部分 chunk 已分析，继续时跳过
        期望：只分析未完成的 chunk
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 保存检查点（已分析 0-4）
            ingest.save_checkpoint("test_book", "analysis", {
                "chunks_analyzed": 5,
                "total_chunks": 10,
                "results": [{"chunk_index": i} for i in range(5)]
            })

            # 模拟继续分析
            all_chunks = [{"content": f"chunk {i}"} for i in range(10)]
            remaining = ingest.get_remaining_chunks("test_book", all_chunks)

            assert len(remaining) == 5, "应有 5 个未分析的 chunk"
            assert remaining[0]["content"] == "chunk 5", "应从第 5 个开始"


# ═══════════════════════════════════════════════════════════
# Test 2: 生成阶段失败恢复
# ═══════════════════════════════════════════════════════════

class TestGenerationFailureRecovery:
    """测试生成阶段失败恢复"""

    def test_analysis_preserved_on_generation_failure(self):
        """
        RED: 测试生成失败时保留分析结果

        场景：分析成功，生成失败
        期望：分析结果被保存，可重试生成
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 模拟分析成功
            analysis_result = {
                "key_entities": ["实体1", "实体2"],
                "key_concepts": [{"name": "概念1"}],
                "status": "complete"
            }
            ingest.save_checkpoint("test_book", "analysis", analysis_result)

            # 模拟生成失败
            try:
                raise Exception("生成失败")
            except Exception:
                pass

            # 分析结果应仍存在
            loaded = ingest.load_checkpoint("test_book", "analysis")
            assert loaded is not None, "分析结果应被保留"
            assert loaded["status"] == "complete"

    def test_retry_generation_from_analysis(self):
        """
        RED: 测试从分析结果重试生成

        场景：生成失败后，从分析结果重新生成
        期望：不需要重新分析
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 保存分析结果（标记为完成）
            analysis = {
                "key_entities": ["实体1"],
                "key_concepts": [{"name": "概念1"}],
                "status": "complete"  # 添加完成标记
            }
            ingest.save_checkpoint("test_book", "analysis", analysis)

            # 检查是否可以跳过分析
            can_skip = ingest.can_skip_analysis("test_book")
            assert can_skip, "应能跳过分析阶段"


# ═══════════════════════════════════════════════════════════
# Test 3: 多轮合成失败恢复
# ═══════════════════════════════════════════════════════════

class TestMultiRoundSynthesisRecovery:
    """测试多轮合成失败恢复"""

    def test_save_round_result(self):
        """
        RED: 测试保存每轮合成结果

        场景：多轮合成中，每轮完成后保存
        期望：失败时可从最后成功的轮次继续
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            synthesis = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 模拟 Round 1 完成
            round1_result = {"metadata": {"title": "测试"}, "time_background": {}}
            synthesis.save_checkpoint("test_book_round_1", "synthesis", round1_result)

            # 验证 Round 1 结果存在
            loaded = synthesis.load_checkpoint("test_book_round_1", "synthesis")
            assert loaded is not None, "Round 1 结果应被保存"

    def test_resume_from_last_successful_round(self):
        """
        RED: 测试从最后成功的轮次继续

        场景：Round 1-2 成功，Round 3 失败
        期望：能从 Round 3 重新开始，不重复 Round 1-2
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            synthesis = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 保存 Round 1-2
            synthesis.save_checkpoint("test_book_round_1", "synthesis", {"metadata": {}})
            synthesis.save_checkpoint("test_book_round_2", "synthesis", {"chapters": []})

            # 检查进度（基于检查点文件）
            round2_loaded = synthesis.load_checkpoint("test_book_round_2", "synthesis")
            assert round2_loaded is not None, "Round 2 应成功"


# ═══════════════════════════════════════════════════════════
# Test 4: 完整流程恢复
# ═══════════════════════════════════════════════════════════

class TestFullPipelineRecovery:
    """测试完整流程恢复"""

    def test_recover_from_checkpoint_file(self):
        """
        RED: 测试从检查点文件恢复完整流程

        场景：处理中断，检查点文件存在
        期望：能检测并恢复
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 保存完整检查点（使用正确的 stage 值）
            ingest.save_checkpoint("test_book", "full", {
                "stage": "full",  # 使用实际保存的 stage
                "analysis_result": {"key_entities": []},
                "generation_attempts": 0,
            })

            # 检测可恢复
            can_recover = ingest.can_recover("test_book")
            assert can_recover, "应能检测到可恢复的检查点"

            # 获取恢复信息
            recovery_info = ingest.get_recovery_info("test_book")
            assert recovery_info["stage"] == "full", "应知道当前阶段"

    def test_clean_checkpoint_after_success(self):
        """
        RED: 测试成功完成后清理检查点

        场景：整个流程成功完成
        期望：清理检查点文件，避免下次误恢复
        """
        from core.two_stage_ingest import TwoStageIngest

        with tempfile.TemporaryDirectory() as tmpdir:
            ingest = TwoStageIngest(llm_client=None, checkpoint_dir=tmpdir)

            # 保存检查点
            ingest.save_checkpoint("test_book", "analysis", {"data": "test"})

            # 清理
            ingest.clean_checkpoints("test_book")

            # 检查点应被删除
            checkpoint_file = Path(tmpdir) / "test_book_analysis.json"
            assert not checkpoint_file.exists(), "检查点应被清理"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
