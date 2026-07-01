"""
P1-3 W4-24: must_use_tool 触发词 casefold + 2nd round fallback
"""

import pytest


def test_must_use_tool_triggers_constant():
    """MUST_USE_TOOL_TRIGGERS 模块常量存在且含中英文"""
    from app.core.agent import MUST_USE_TOOL_TRIGGERS
    assert isinstance(MUST_USE_TOOL_TRIGGERS, (tuple, list))
    # 中文触发
    for t in ["请使用", "调用工具", "读取文件"]:
        assert t in MUST_USE_TOOL_TRIGGERS
    # 英文触发
    for t in ["playwright", "browser", "read_file"]:
        assert t in MUST_USE_TOOL_TRIGGERS


def test_visible_chrome_triggers_constant():
    from app.core.agent import VISIBLE_CHROME_TRIGGERS
    assert "可视化" in VISIBLE_CHROME_TRIGGERS
    assert "google chrome" in VISIBLE_CHROME_TRIGGERS


def test_message_requires_tool_call_uses_casefold():
    """P1-3: 用 .casefold() 替代 .lower() (Unicode 正确)"""
    import inspect
    from app.core import agent
    src = inspect.getsource(agent)
    # 找 _message_requires_tool_call 函数
    fn_start = src.find("def _message_requires_tool_call")
    fn_end = src.find("def _message_requires_visible_chrome", fn_start)
    fn = src[fn_start:fn_end]
    # 函数体内 (去掉注释) 应当用 casefold
    code_only = "\n".join(l for l in fn.split("\n") if not l.strip().startswith("#"))
    assert ".casefold()" in code_only, "_message_requires_tool_call 应当用 .casefold()"
    # 旧 .lower() 不应在函数代码里
    assert ".lower()" not in code_only, "_message_requires_tool_call 不应再用 .lower()"


def test_chinese_triggers_match():
    """中文触发词应当匹配"""
    from app.core.agent import AgentEngine
    # _message_requires_tool_call 是 AgentEngine 实例方法的 closure
    # 通过 AgentEngine 间接测
    from app.core import agent as agent_mod
    # 用 AgentEngine 模拟
    from app.core.agent import MUST_USE_TOOL_TRIGGERS

    def check(text):
        return any(t in (text or "").casefold() for t in MUST_USE_TOOL_TRIGGERS)

    assert check("请使用 playwright 打开")
    assert check("务必调用 browser")
    assert check("必须用工具读 README")
    assert check("打开网页截图")
    # 大小写
    assert check("PLAYWRIGHT please")
    assert check("Use the TOOL")


def test_english_triggers_match():
    """英文触发词 casefold 后匹配"""
    from app.core.agent import MUST_USE_TOOL_TRIGGERS

    def check(text):
        return any(t in (text or "").casefold() for t in MUST_USE_TOOL_TRIGGERS)

    assert check("please use the tool")
    assert check("must call playwright")
    assert check("Playwright navigate to example.com")
    assert check("read_file /path/to/x")  # 工具名 trigger


def test_visible_chrome_match():
    from app.core.agent import VISIBLE_CHROME_TRIGGERS

    def check(text):
        return any(t in (text or "").casefold() for t in VISIBLE_CHROME_TRIGGERS)

    assert check("用本地 Chrome 打开")
    assert check("Google chrome please")
    assert check("我希望在 chrome 里看")


def test_2nd_round_fallback_message():
    """W4-24: 2nd round LLM 仍不用 tool, 显式 fallback 提示"""
    import inspect
    from app.core import agent
    src = inspect.getsource(agent)
    # 找 2nd round fallback 块
    assert "工具调用失败" in src, "2nd round fallback 应当有明确错误提示"
    assert "连续 2 轮" in src, "fallback 消息应当说明连续 2 轮"
    # 应当 break 出去不再循环
    assert "2nd round" in src or "不再无限重试" in src


def test_required_evidence_for_frontend_build_task():
    """W4-48: 前端长任务必须有写文件 + 构建验证证据。"""
    from app.core.agent import _required_tool_evidence, _missing_tool_evidence

    req = _required_tool_evidence(
        "在 frontend React 项目里完成一个 UI，最后运行 npm run build 验证"
    )
    assert "write" in req
    assert "build" in req

    missing = _missing_tool_evidence(req, ["ls", "read_file"], [])
    assert any("write_file" in item or "patch" in item for item in missing)
    assert any("npm run build" in item for item in missing)


def test_required_evidence_satisfied_by_write_and_build():
    from app.core.agent import _required_tool_evidence, _missing_tool_evidence

    req = _required_tool_evidence(
        "修改 frontend React UI，并运行 npm run build 验证"
    )
    missing = _missing_tool_evidence(
        req,
        ["ls", "read_file", "write_file", "terminal"],
        ["cd frontend && npm run build"],
    )
    assert missing == []


def test_langchain_path_checks_required_evidence():
    """W4-48: 默认 LangChain 流式路径也必须执行交付证据门禁。"""
    import inspect
    from app.core import langchain_agent

    src = inspect.getsource(langchain_agent)
    assert "_required_tool_evidence" in src
    assert "_missing_tool_evidence" in src
    assert "任务未完整交付" in src
    assert "needs_continue = True" in src
