from __future__ import annotations

from contextlib import contextmanager
import logging
import time
from typing import Any, Iterator


logger = logging.getLogger(__name__)


def now_perf_counter() -> float:
    """返回单调递增时间，只用于计算耗时，不用于展示真实时间。"""
    return time.perf_counter()


def elapsed_ms(start: float, end: float | None = None) -> float:
    """把 perf_counter 的差值转换成毫秒，并保留两位小数。"""
    end_time = now_perf_counter() if end is None else end
    return round(max((end_time - start) * 1000, 0), 2)


def record_trace_stage(
    state: dict[str, Any],
    stage: str,
    duration_ms: float,
    status: str = "success",
    **extra: Any,
) -> dict[str, Any]:
    """把阶段耗时写入 state，并输出一行便于控制台检索的结构化日志。"""
    trace_item = {
        "stage": stage,
        "duration_ms": round(float(duration_ms), 2),
        "status": status,
    }
    trace_item.update({key: value for key, value in extra.items() if value is not None})
    state.setdefault("trace", []).append(trace_item)

    trace_id = state.get("trace_id", "")
    log_name = "audit_trace_stage_failed" if status == "failed" else "audit_trace_stage_done"
    logger.info(
        "%s trace_id=%s stage=%s duration_ms=%.2f status=%s extra=%s",
        log_name,
        trace_id,
        stage,
        trace_item["duration_ms"],
        status,
        {key: value for key, value in trace_item.items() if key not in {"stage", "duration_ms", "status"}},
    )
    return trace_item


@contextmanager
def timed_stage(state: dict[str, Any], stage: str, **extra: Any) -> Iterator[None]:
    """用上下文管理器记录一段代码的耗时，异常时先写 trace 再继续抛出。"""
    start = now_perf_counter()
    try:
        yield
    except Exception as exc:
        record_trace_stage(state, stage, elapsed_ms(start), status="failed", error=exc.__class__.__name__, **extra)
        raise
    record_trace_stage(state, stage, elapsed_ms(start), status="success", **extra)
