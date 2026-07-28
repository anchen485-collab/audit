import logging
from pathlib import Path
from time import perf_counter
from typing import Callable
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.audit.nodes import (
    audit_records_node,
    build_summary_node,
    export_result_node,
    query_company_info_node,
    read_category_node,
    read_employee_node,
)
from app.companies.providers.mock import MockCompanyInfoProvider
from app.companies.providers.base import CompanyInfoProvider
from app.core.models import AuditGraphState
from app.core.trace import elapsed_ms, record_trace_stage


logger = logging.getLogger(__name__)


def _timed_node(stage: str, node_func: Callable[[AuditGraphState], AuditGraphState]):
    """包装 LangGraph 节点，统一记录每个阶段的耗时。"""

    def wrapper(state: AuditGraphState) -> AuditGraphState:
        start = perf_counter()
        try:
            result = node_func(state)
        except Exception as exc:
            trace_state = {"trace_id": state.get("trace_id"), "trace": list(state.get("trace", []))}
            record_trace_stage(trace_state, stage, elapsed_ms(start), status="failed", error=exc.__class__.__name__)
            raise

        trace_state = {"trace_id": state.get("trace_id"), "trace": list(state.get("trace", []))}
        record_trace_stage(trace_state, stage, elapsed_ms(start), status="success")
        result["trace"] = trace_state["trace"]
        return result

    return wrapper


def build_audit_graph():
    """构建 version1.0 的 LangGraph 审计流程。"""
    workflow = StateGraph(AuditGraphState)
    workflow.add_node("read_employee", _timed_node("read_employee", read_employee_node))
    workflow.add_node("read_category", _timed_node("read_category", read_category_node))
    workflow.add_node("query_company_info", _timed_node("query_company_info", query_company_info_node))
    workflow.add_node("audit_records", _timed_node("audit_records", audit_records_node))
    workflow.add_node("build_summary", _timed_node("build_summary", build_summary_node))
    workflow.add_node("export_result", _timed_node("export_result", export_result_node))

    workflow.add_edge(START, "read_employee")
    workflow.add_edge("read_employee", "read_category")
    workflow.add_edge("read_category", "query_company_info")
    workflow.add_edge("query_company_info", "audit_records")
    workflow.add_edge("audit_records", "build_summary")
    workflow.add_edge("build_summary", "export_result")
    workflow.add_edge("export_result", END)
    return workflow.compile()


def run_audit_workflow(
    employee_file: str | Path,
    category_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    provider: CompanyInfoProvider | None = None,
    job_id: str | None = None,
) -> AuditGraphState:
    """运行完整审计流程，并返回最终状态。"""
    if output_dir is None:
        raise ValueError("必须提供审计结果输出目录")
    workflow_start = perf_counter()
    graph = build_audit_graph()
    initial_state: AuditGraphState = {
        "employee_file": str(employee_file),
        "output_dir": str(output_dir),
        "job_id": job_id or f"审计结果_{uuid4().hex[:8]}",
        "trace_id": f"audit_{uuid4().hex[:12]}",
        "provider": provider or MockCompanyInfoProvider(),
        "errors": [],
        "steps": [],
        "trace": [],
    }
    if category_file:
        initial_state["category_file"] = str(category_file)
    logger.info(
        "audit_workflow_start 审计流程开始 job_id=%s trace_id=%s employee_file=%s category_source=%s provider=%s",
        initial_state["job_id"],
        initial_state["trace_id"],
        initial_state["employee_file"],
        initial_state.get("category_file") or "configured_json",
        initial_state["provider"].__class__.__name__,
    )
    final_state = graph.invoke(initial_state)
    total_duration_ms = elapsed_ms(workflow_start)
    record_trace_stage(final_state, "audit_workflow", total_duration_ms, status="success")
    logger.info(
        "audit_workflow_done 审计流程完成 job_id=%s trace_id=%s output_path=%s result_count=%s total_duration_ms=%.2f",
        final_state.get("job_id"),
        final_state.get("trace_id"),
        final_state.get("output_path"),
        len(final_state.get("results", [])),
        total_duration_ms,
    )
    return final_state
