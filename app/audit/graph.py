from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.audit.nodes import (
    build_summary_node,
    export_result_node,
    match_rules_node,
    query_company_node,
    read_category_node,
    read_employee_node,
)
from app.company.mock_provider import MockCompanyInfoProvider
from app.company.provider import CompanyInfoProvider
from app.core.models import AuditGraphState


def build_audit_graph():
    """构建 version1.0 的 LangGraph 审计流程。"""
    workflow = StateGraph(AuditGraphState)
    workflow.add_node("read_employee", read_employee_node)
    workflow.add_node("read_category", read_category_node)
    workflow.add_node("query_company", query_company_node)
    workflow.add_node("match_rules", match_rules_node)
    workflow.add_node("build_summary", build_summary_node)
    workflow.add_node("export_result", export_result_node)

    workflow.add_edge(START, "read_employee")
    workflow.add_edge("read_employee", "read_category")
    workflow.add_edge("read_category", "query_company")
    workflow.add_edge("query_company", "match_rules")
    workflow.add_edge("match_rules", "build_summary")
    workflow.add_edge("build_summary", "export_result")
    workflow.add_edge("export_result", END)
    return workflow.compile()


def run_audit_workflow(
    employee_file: str | Path,
    category_file: str | Path,
    output_dir: str | Path,
    provider: CompanyInfoProvider | None = None,
    job_id: str | None = None,
) -> AuditGraphState:
    """运行完整审计流程，并返回最终状态。"""
    graph = build_audit_graph()
    initial_state: AuditGraphState = {
        "employee_file": str(employee_file),
        "category_file": str(category_file),
        "output_dir": str(output_dir),
        "job_id": job_id or f"审计结果_{uuid4().hex[:8]}",
        "provider": provider or MockCompanyInfoProvider(),
        "errors": [],
        "steps": [],
    }
    return graph.invoke(initial_state)
