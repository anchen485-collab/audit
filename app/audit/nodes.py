from pathlib import Path

from app.audit.rules import audit_record, clean_company_name
from app.audit.summary import build_person_summary
from app.company.provider import CompanyInfoProvider
from app.core.models import AuditGraphState
from app.excel.category_reader import read_category_rules
from app.excel.input_reader import read_employee_excel
from app.excel.result_writer import write_audit_result_excel


def read_employee_node(state: AuditGraphState) -> AuditGraphState:
    records = read_employee_excel(state["employee_file"])
    return {"records": records, "steps": state.get("steps", []) + [f"读取员工记录 {len(records)} 条"]}


def read_category_node(state: AuditGraphState) -> AuditGraphState:
    rules = read_category_rules(state["category_file"])
    return {"rules": rules, "steps": state.get("steps", []) + [f"读取分类规则 {len(rules)} 条"]}


def query_company_node(state: AuditGraphState) -> AuditGraphState:
    provider: CompanyInfoProvider = state["provider"]
    infos = {}
    for record in state["records"]:
        company_name = clean_company_name(record.company_raw)
        if company_name not in infos:
            record.company_name = company_name
            infos[company_name] = provider.get_company_info_for_record(record)
    return {"company_infos": infos, "steps": state.get("steps", []) + [f"查询企业 {len(infos)} 家"]}


def match_rules_node(state: AuditGraphState) -> AuditGraphState:
    infos = state["company_infos"]
    results = []
    for record in state["records"]:
        company_name = clean_company_name(record.company_raw)
        results.append(audit_record(record, state["rules"], infos.get(company_name)))
    return {"results": results, "steps": state.get("steps", []) + [f"完成审计 {len(results)} 条"]}


def build_summary_node(state: AuditGraphState) -> AuditGraphState:
    summary = {"person_summary": build_person_summary(state["results"])}
    return {"summary": summary, "steps": state.get("steps", []) + ["生成质量汇总"]}


def export_result_node(state: AuditGraphState) -> AuditGraphState:
    output_dir = Path(state["output_dir"])
    job_id = state.get("job_id") or "audit_result"
    output_path = output_dir / f"{job_id}.xlsx"
    write_audit_result_excel(state["results"], output_path)
    return {"output_path": str(output_path), "steps": state.get("steps", []) + ["导出审计结果 Excel"]}
