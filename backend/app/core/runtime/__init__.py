"""Runtime 框架 (W5-7)

统一 trace 追踪 + runtime 维护层。目前包含:
  - trace: trace/span 数据模型 + contextvar 传播 + SQLite 落库

设计原则:
  - 循环/工具代码只调 start_trace / start_span, 不感知落库细节
  - 全局开关关闭时零开销 (不建连接不写库)
  - 复用 app.paths 数据路径, 自建表 (不依赖未接线的 migration runner)
"""

from app.core.runtime.trace import (
    TraceStore,
    configure_runtime,
    reset_runtime,
    start_trace,
    start_span,
    record_span,
    current_trace_id,
    current_span_id,
    get_store,
    is_enabled,
)


from app.core.runtime.ipc import (
    SubprocessBroker,
    AsyncCallGuard,
    CircuitBreaker,
    BreakerState,
    IPCResult,
    get_broker,
    reset_broker,
    get_guard,
    reset_guard,
)
from app.core.runtime.planner import (
    Plan,
    PlanStep,
    StepStatus,
    build_plan_from_llm,
    build_plan_heuristic,
)
from app.core.runtime.reflection import (
    Reflector,
    ReflectionVerdict,
    Decision,
    get_reflector,
)

__all__ = [
    "TraceStore",
    "configure_runtime",
    "reset_runtime",
    "start_trace",
    "start_span",
    "record_span",
    "current_trace_id",
    "current_span_id",
    "get_store",
    "is_enabled",
    # ipc
    "SubprocessBroker",
    "AsyncCallGuard",
    "CircuitBreaker",
    "BreakerState",
    "IPCResult",
    "get_broker",
    "reset_broker",
    "get_guard",
    "reset_guard",
    # planner
    "Plan",
    "PlanStep",
    "StepStatus",
    "build_plan_from_llm",
    "build_plan_heuristic",
    # reflection
    "Reflector",
    "ReflectionVerdict",
    "Decision",
    "get_reflector",
]
