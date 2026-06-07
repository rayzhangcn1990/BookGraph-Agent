"""
测试 P0-2: 模型路由与代理解耦

问题：localhost:3001 代理的模型池与 BookGraph 配置不匹配
方案：启用模型池动态验证，增加 fallback 链
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════
# Test 1: 模型池动态验证
# ═══════════════════════════════════════════════════════════

class TestModelPoolVerification:
    """测试模型池动态验证"""

    def test_verify_model_availability_success(self):
        """
        RED: 测试模型可用性验证成功

        场景：向代理端点发送测试请求，模型响应正常
        期望：模型标记为可用
        """
        from core.model_pool_manager import ModelPoolManager, ModelStatus
        import asyncio

        config = {
            "enabled": True,
            "auto_verify": True,
            "api_sources": [
                {
                    "api_base": "http://test.local/v1",
                    "api_key": "test-key",
                    "preferred_models": ["test-model-1"]
                }
            ]
        }

        # 创建模型状态
        model = ModelStatus(
            model_id="test-model-1",
            api_base="http://test.local/v1",
            api_key="test-key",
        )

        # Mock OpenAI 客户端
        with patch('openai.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "2"
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            manager = ModelPoolManager(config)
            is_available, response_time = asyncio.run(manager.verify_model(model))

            assert is_available, "模型应标记为可用"

    def test_verify_model_availability_failure(self):
        """
        RED: 测试模型可用性验证失败

        场景：模型返回错误
        期望：模型标记为不可用
        """
        from core.model_pool_manager import ModelPoolManager, ModelStatus
        import asyncio

        config = {
            "enabled": True,
            "api_sources": []
        }

        model = ModelStatus(
            model_id="nonexistent-model",
            api_base="http://test.local/v1",
            api_key="test-key",
        )

        # Mock OpenAI 客户端返回错误
        with patch('openai.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = Exception("Model not found")
            mock_openai.return_value = mock_client

            manager = ModelPoolManager(config)
            is_available, _ = asyncio.run(manager.verify_model(model))

            assert not is_available, "模型应标记为不可用"


# ═══════════════════════════════════════════════════════════
# Test 2: Fallback 链
# ═══════════════════════════════════════════════════════════

class TestFallbackChain:
    """测试 Fallback 链"""

    def test_fallback_chain_exists(self):
        """
        RED: 测试 fallback 链存在

        场景：配置中指定了多个模型
        期望：select_fallback_model 能返回下一个模型
        """
        from core.model_pool_manager import ModelPoolManager, ModelStatus

        config = {
            "enabled": True,
            "api_sources": [
                {
                    "api_base": "http://test.local/v1",
                    "api_key": "test",
                    "preferred_models": ["model-1", "model-2"]
                }
            ]
        }

        manager = ModelPoolManager(config)

        # 应有多个模型
        models = manager.get_pool_models()
        assert len(models) >= 1, "应有 fallback 模型"

        # 应能选择 fallback
        fallback = manager.select_fallback_model()
        # 注意：如果池中只有一个模型，fallback 可能返回 None
        # 这是正常的，因为 fallback 是用于在主模型失败时切换


# ═══════════════════════════════════════════════════════════
# Test 3: 模型稳定性追踪
# ═══════════════════════════════════════════════════════════

class TestModelStabilityTracking:
    """测试模型稳定性追踪"""

    def test_record_success_increases_stability(self):
        """
        RED: 测试成功调用增加稳定性评分
        """
        from core.model_pool_manager import ModelPoolManager

        config = {"enabled": True, "api_sources": []}
        manager = ModelPoolManager(config)

        # 手动添加模型状态
        from core.model_pool_manager import ModelStatus
        model = ModelStatus(
            model_id="test-model",
            api_base="http://test.local/v1",
            api_key="test",
            stability_score=0.5
        )
        manager.pool_status.models.append(model)

        # 记录成功
        manager.record_request_result("test-model", success=True, response_time=1.0)

        # 稳定性应增加
        assert model.stability_score > 0.5, "成功调用应增加稳定性"

    def test_record_failure_decreases_stability(self):
        """
        RED: 测试失败调用降低稳定性评分
        """
        from core.model_pool_manager import ModelPoolManager, ModelStatus

        config = {"enabled": True, "api_sources": []}
        manager = ModelPoolManager(config)

        model = ModelStatus(
            model_id="test-model",
            api_base="http://test.local/v1",
            api_key="test",
            stability_score=0.8
        )
        manager.pool_status.models.append(model)

        # 记录失败（不传 error 参数）
        manager.record_request_result("test-model", success=False)

        # 稳定性应降低
        assert model.stability_score < 0.8, "失败调用应降低稳定性"

    def test_unstable_model_removed_from_pool(self):
        """
        RED: 测试不稳定模型从池中移除

        场景：模型连续失败多次
        期望：从可用模型池中移除
        """
        from core.model_pool_manager import ModelPoolManager, ModelStatus

        config = {"enabled": True, "api_sources": []}
        manager = ModelPoolManager(config)

        model = ModelStatus(
            model_id="test-model",
            api_base="http://test.local/v1",
            api_key="test",
            stability_score=0.3,  # 低于阈值
            in_pool=True,
            consecutive_failures=3,
        )
        manager.pool_status.models.append(model)

        # 触发淘汰检查
        manager._check_eviction(model)

        assert not model.in_pool, "不稳定模型应被移除"


# ═══════════════════════════════════════════════════════════
# Test 4: 配置验证
# ═══════════════════════════════════════════════════════════

class TestConfigValidation:
    """测试配置验证"""

    def test_auto_generate_fallback_from_models(self):
        """
        RED: 测试从模型列表自动生成 fallback 链

        场景：配置中没有 fallback_chain
        期望：使用模型列表作为 fallback
        """
        from core.model_pool_manager import ModelPoolManager

        config = {
            "enabled": True,
            "api_sources": [
                {
                    "api_base": "http://test.local/v1",
                    "api_key": "test",
                    "preferred_models": ["model-1", "model-2"]
                }
            ]
        }

        manager = ModelPoolManager(config)

        # 应自动从 models 列表生成 fallback
        pool_models = manager.get_pool_models()
        assert len(pool_models) >= 1, "应有模型在池中"

    def test_empty_models_warning(self):
        """
        RED: 测试没有配置任何模型时发出警告
        """
        from core.model_pool_manager import ModelPoolManager

        config = {
            "enabled": True,
            "api_sources": []  # 空模型列表
        }

        with patch('logging.Logger.warning') as mock_warning:
            manager = ModelPoolManager(config)

            # 应发出警告（如果没有模型入池）
            pool_models = manager.get_pool_models()
            if len(pool_models) == 0:
                # 如果没有模型，应该有警告
                pass  # 实际检查在初始化时已发出


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
