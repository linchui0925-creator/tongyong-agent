"""
Test SKIP_LLM_VALIDATION env var in lifespan._startup_llm (W4-28)

验证:
- SKIP_LLM_VALIDATION=1 → 立即返回, 不调 llm.initialize()
- 不设 env → 调 llm.initialize() (5s wait_for 包裹)
- initialize 超时 → 5s 后 TimeoutError 被 catch, 记 warning
- initialize 抛异常 → 被 catch, 不让 app 启动失败
- app 无 engine → 直接返回
"""
import asyncio
import os
import pytest

from app.lifespan import _startup_llm


def _make_app(initialize_fn):
    """构造带 mock agent_engine 的 app"""
    from unittest.mock import MagicMock
    app = MagicMock()
    app.extra = {
        "agent_engine": MagicMock(llm=MagicMock(initialize=initialize_fn))
    }
    return app


class TestSkipLLMValidation:
    """W4-28: lifespan._startup_llm SKIP 开关 + 5s fast-fail"""

    def setup_method(self):
        """每个测试前清环境变量"""
        os.environ.pop("SKIP_LLM_VALIDATION", None)

    def teardown_method(self):
        os.environ.pop("SKIP_LLM_VALIDATION", None)

    def test_skip_env_returns_immediately(self):
        """SKIP_LLM_VALIDATION=1 应立即返回, 不调用 llm.initialize()"""
        from unittest.mock import AsyncMock
        os.environ["SKIP_LLM_VALIDATION"] = "1"
        initialize_mock = AsyncMock()
        app = _make_app(initialize_mock)
        asyncio.run(_startup_llm(app))
        initialize_mock.assert_not_called()

    def test_no_skip_calls_initialize(self):
        """不设 SKIP 时应调 llm.initialize()"""
        from unittest.mock import AsyncMock
        initialize_mock = AsyncMock(return_value=True)
        app = _make_app(initialize_mock)
        asyncio.run(_startup_llm(app))
        initialize_mock.assert_called_once()

    def test_initialize_timeout_caught(self):
        """initialize 超时 5s 应被 wait_for catch, 不抛 TimeoutError"""
        async def slow_init():
            await asyncio.sleep(10)

        app = _make_app(slow_init)
        # 关键: 不应抛 TimeoutError 到外面
        asyncio.run(_startup_llm(app))

    def test_initialize_exception_caught(self):
        """initialize 抛异常应被 catch, 不让 app 启动失败"""
        async def bad_init():
            raise RuntimeError("network unreachable")

        app = _make_app(bad_init)
        asyncio.run(_startup_llm(app))

    def test_no_engine_returns_silently(self):
        """app 没 engine 时直接返回"""
        from unittest.mock import MagicMock
        app = MagicMock()
        app.extra = {}
        asyncio.run(_startup_llm(app))

    def test_skip_overrides_engine(self):
        """即使有 engine, SKIP 时也不调 initialize"""
        from unittest.mock import AsyncMock
        os.environ["SKIP_LLM_VALIDATION"] = "1"
        initialize_mock = AsyncMock()
        app = _make_app(initialize_mock)
        asyncio.run(_startup_llm(app))
        initialize_mock.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
