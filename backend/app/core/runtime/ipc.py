"""Runtime IPC / 进程隔离层 (W5-8)

给 runtime 补上参考架构里缺失的 "IPC 通信层 + 工具沙箱进程":
  - 在**独立子进程**里执行可调用逻辑 (真正的进程隔离, 崩溃/死循环不拖垮主进程)
  - 每次调用带 **超时熔断** (硬 kill 子进程)
  - 每个 target 带 **熔断器 (circuit breaker)**: 连续失败 N 次后短路, 冷却后半开重试
  - 与 runtime trace 打通: 每次隔离调用产一个 `ipc.call` span

设计取舍:
  - 不引入容器/命名空间 (环境不具备); 用 `multiprocessing` spawn 子进程做进程级隔离,
    这是纯 Python、跨平台、零外部依赖能拿到的最强隔离。
  - broker 只负责 "把一个可 pickle 的 callable + 参数丢进子进程, 限时拿回结果";
    工具本身是否可 pickle 由调用方保证 (顶层函数 / 可导入路径最稳)。
  - 任何 IPC 失败都以结构化 `IPCResult` 返回, 不抛给主流程 (fail safe)。
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue as _queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 用 spawn 保证子进程干净 (不继承主进程线程/锁状态), 跨平台一致。
try:
    _MP_CTX = mp.get_context("spawn")
except Exception:  # 极端环境兜底
    _MP_CTX = mp


class BreakerState(str, Enum):
    CLOSED = "closed"      # 正常放行
    OPEN = "open"          # 短路, 直接拒绝
    HALF_OPEN = "half_open"  # 冷却后放一个试探请求


@dataclass
class IPCResult:
    ok: bool
    value: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    elapsed_ms: float = 0.0
    timed_out: bool = False
    short_circuited: bool = False


@dataclass
class CircuitBreaker:
    """每个 target 一个熔断器。

    failure_threshold 次连续失败后 OPEN; 冷却 reset_timeout 秒后转 HALF_OPEN;
    HALF_OPEN 下成功一次 → CLOSED, 失败一次 → 立刻回 OPEN。
    """
    failure_threshold: int = 3
    reset_timeout: float = 30.0
    _state: BreakerState = field(default=BreakerState.CLOSED)
    _failures: int = 0
    _opened_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._eval_state()

    def _eval_state(self) -> BreakerState:
        if self._state == BreakerState.OPEN and (time.time() - self._opened_at) >= self.reset_timeout:
            self._state = BreakerState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        with self._lock:
            return self._eval_state() != BreakerState.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = time.time()


def _worker_entry(func: Callable, args: tuple, kwargs: dict, out_q) -> None:
    """子进程入口: 执行 func 并把结果/异常塞回队列。"""
    try:
        result = func(*args, **(kwargs or {}))
        out_q.put(("ok", result))
    except Exception as e:  # noqa: BLE001 - 必须捕获一切传回主进程
        out_q.put(("err", f"{type(e).__name__}: {e}"))


class SubprocessBroker:
    """限时、隔离、可熔断的子进程调用 broker。

    用法:
        broker = SubprocessBroker()
        res = broker.call("heavy_tool", heavy_fn, args=(...), timeout=10)
        if res.ok: use(res.value)
    """

    def __init__(self, default_timeout: float = 30.0,
                 failure_threshold: int = 3, reset_timeout: float = 30.0):
        self.default_timeout = default_timeout
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def _breaker(self, target: str) -> CircuitBreaker:
        with self._lock:
            b = self._breakers.get(target)
            if b is None:
                b = CircuitBreaker(
                    failure_threshold=self._failure_threshold,
                    reset_timeout=self._reset_timeout,
                )
                self._breakers[target] = b
            return b

    def breaker_state(self, target: str) -> BreakerState:
        return self._breaker(target).state

    def call(self, target: str, func: Callable, args: tuple = (),
             kwargs: Optional[dict] = None, timeout: Optional[float] = None) -> IPCResult:
        """在独立子进程里执行 func, 限时 timeout 秒。

        - 熔断器 OPEN → 直接返回 short_circuited, 不起进程。
        - 超时 → kill 子进程, 记失败, timed_out=True。
        - 子进程内异常 → 记失败, 结构化返回。
        """
        breaker = self._breaker(target)
        t0 = time.time()

        _rt = _get_trace_mod()
        span_cm = _rt.start_span("ipc.call", {"target": target}) if _rt else None
        span = span_cm.__enter__() if span_cm else None

        def _finish(res: IPCResult):
            if span is not None:
                span.attributes["ok"] = res.ok
                span.attributes["timed_out"] = res.timed_out
                span.attributes["short_circuited"] = res.short_circuited
                span.attributes["breaker"] = breaker.state.value
                if not res.ok:
                    span.status = "error"
                    span.error = (res.error or "")[:500]
            if span_cm is not None:
                span_cm.__exit__(None, None, None)
            return res

        if not breaker.allow():
            return _finish(IPCResult(
                ok=False, error=f"circuit breaker OPEN for '{target}'",
                error_type="CircuitOpen", short_circuited=True,
                elapsed_ms=round((time.time() - t0) * 1000, 3),
            ))

        timeout = timeout if timeout is not None else self.default_timeout
        out_q = _MP_CTX.Queue()
        proc = _MP_CTX.Process(target=_worker_entry, args=(func, args, kwargs, out_q))
        try:
            proc.start()
        except Exception as e:  # 起进程本身失败 (不可 pickle 等)
            breaker.record_failure()
            return _finish(IPCResult(
                ok=False, error=f"failed to spawn worker: {e}",
                error_type="SpawnError",
                elapsed_ms=round((time.time() - t0) * 1000, 3),
            ))

        try:
            payload = out_q.get(timeout=timeout)
        except _queue.Empty:
            _kill(proc)
            breaker.record_failure()
            return _finish(IPCResult(
                ok=False, error=f"call to '{target}' timed out after {timeout}s",
                error_type="Timeout", timed_out=True,
                elapsed_ms=round((time.time() - t0) * 1000, 3),
            ))
        finally:
            proc.join(timeout=1.0)
            if proc.is_alive():
                _kill(proc)

        elapsed = round((time.time() - t0) * 1000, 3)
        kind, data = payload
        if kind == "ok":
            breaker.record_success()
            return _finish(IPCResult(ok=True, value=data, elapsed_ms=elapsed))
        breaker.record_failure()
        return _finish(IPCResult(ok=False, error=str(data), error_type="WorkerError", elapsed_ms=elapsed))


class AsyncCallGuard:
    """给**进程内 async 工具**加治理: 超时 + 每 target 熔断器 + trace span。

    说明: 进程内 async 工具依赖当前 event loop / 会话 contextvar / 闭包, 无法安全丢进
    spawn 子进程 (会破坏会话隔离 + 不可 pickle)。真正危险的负载 (如 terminal 执行的
    命令) 本身已在各工具内部起子进程。这里补的是 tool-manager 边界的两条 IPC 语义:
      - 超时: `asyncio.wait_for` 限时, 卡死的 handler 不会永久挂起 ReAct 循环
      - 熔断: 某工具连续失败 → 短路一段时间, 避免反复踩同一个坏工具空转
    失败一律以字符串结果返回 (跟 registry.execute 的错误约定一致), 不抛。
    """

    def __init__(self, default_timeout: float = 60.0,
                 failure_threshold: int = 3, reset_timeout: float = 30.0):
        self.default_timeout = default_timeout
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def _breaker(self, target: str) -> CircuitBreaker:
        with self._lock:
            b = self._breakers.get(target)
            if b is None:
                b = CircuitBreaker(
                    failure_threshold=self._failure_threshold,
                    reset_timeout=self._reset_timeout,
                )
                self._breakers[target] = b
            return b

    def breaker_state(self, target: str) -> BreakerState:
        return self._breaker(target).state

    async def run(self, target: str, coro_factory: Callable[[], Any],
                  timeout: Optional[float] = None,
                  is_error: Optional[Callable[[Any], bool]] = None) -> Any:
        """执行 `await coro_factory()`, 限时 timeout, 记录熔断器。

        - 熔断 OPEN → 直接返回短路错误字符串 (不执行)。
        - 超时 → 返回超时错误字符串, 记失败。
        - handler 抛异常 → 返回错误字符串, 记失败。
        - `is_error(result)` 为 True → 结果本身算失败 (计入熔断), 但原样返回结果。
        """
        import asyncio as _asyncio
        import inspect as _inspect
        breaker = self._breaker(target)
        timeout = timeout if timeout is not None else self.default_timeout

        _rt = _get_trace_mod()
        span_cm = _rt.start_span("tool.guard", {"target": target}) if _rt else None
        span = span_cm.__enter__() if span_cm else None

        def _finish(result: Any, ok: bool, timed_out: bool = False, short: bool = False):
            if span is not None:
                span.attributes["ok"] = ok
                span.attributes["timed_out"] = timed_out
                span.attributes["short_circuited"] = short
                span.attributes["breaker"] = breaker.state.value
                if not ok:
                    span.status = "error"
            if span_cm is not None:
                span_cm.__exit__(None, None, None)
            return result

        if not breaker.allow():
            return _finish(
                f"工具执行失败: 熔断器已打开 (工具 '{target}' 连续失败), 请稍后再试或改用其他方式。",
                ok=False, short=True,
            )

        try:
            _maybe_coro = coro_factory()
            if _inspect.iscoroutine(_maybe_coro):
                result = await _asyncio.wait_for(_maybe_coro, timeout=timeout)
            else:
                result = _maybe_coro
        except _asyncio.TimeoutError:
            breaker.record_failure()
            return _finish(f"工具执行失败: '{target}' 超时 ({timeout}s)。", ok=False, timed_out=True)
        except Exception as e:  # noqa: BLE001
            breaker.record_failure()
            return _finish(f"工具执行失败: {e}", ok=False)

        if is_error is not None and is_error(result):
            breaker.record_failure()
            return _finish(result, ok=False)
        breaker.record_success()
        return _finish(result, ok=True)


_DEFAULT_GUARD: Optional[AsyncCallGuard] = None
_GUARD_LOCK = threading.Lock()


def get_guard() -> AsyncCallGuard:
    global _DEFAULT_GUARD
    with _GUARD_LOCK:
        if _DEFAULT_GUARD is None:
            _DEFAULT_GUARD = AsyncCallGuard()
        return _DEFAULT_GUARD


def reset_guard() -> None:
    global _DEFAULT_GUARD
    with _GUARD_LOCK:
        _DEFAULT_GUARD = None


def _kill(proc) -> None:
    try:
        proc.terminate()
        proc.join(timeout=1.0)
        if proc.is_alive() and hasattr(proc, "kill"):
            proc.kill()
    except Exception:
        pass


def _get_trace_mod():
    try:
        from app.core.runtime import trace as _rt
        return _rt
    except Exception:
        return None


# ── 进程级单例 (可选复用同一组熔断器) ─────────────
_DEFAULT_BROKER: Optional[SubprocessBroker] = None
_DEFAULT_LOCK = threading.Lock()


def get_broker() -> SubprocessBroker:
    global _DEFAULT_BROKER
    with _DEFAULT_LOCK:
        if _DEFAULT_BROKER is None:
            _DEFAULT_BROKER = SubprocessBroker()
        return _DEFAULT_BROKER


def reset_broker() -> None:
    global _DEFAULT_BROKER
    with _DEFAULT_LOCK:
        _DEFAULT_BROKER = None
