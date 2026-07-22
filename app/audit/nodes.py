import logging
from pathlib import Path

from app.agent import build_classification_agent_from_env
from app.audit.rules import audit_record, clean_company_name
from app.audit.summary import build_person_summary
from app.category.rule_index import load_category_rules_from_config
from app.company.provider import CompanyInfoProvider
from app.core.models import AuditGraphState
from app.excel.input_reader import read_employee_excel
from app.excel.result_writer import write_audit_result_excel


logger = logging.getLogger(__name__)


def read_employee_node(state: AuditGraphState) -> AuditGraphState:
    records = read_employee_excel(state["employee_file"])
    logger.info("audit_read_employee_done 员工录入读取完成 file=%s record_count=%s", state["employee_file"], len(records))
    return {"records": records, "steps": state.get("steps", []) + [f"读取员工记录 {len(records)} 条"]}


def read_category_node(state: AuditGraphState) -> AuditGraphState:
    category_source = state.get("category_file")
    rules = load_category_rules_from_config(category_source)
    logger.info("audit_read_category_done 分类规则读取完成 source=%s rule_count=%s", category_source or "configured_json", len(rules))
    return {"rules": rules, "steps": state.get("steps", []) + [f"读取分类规则 {len(rules)} 条"]}


def query_company_node(state: AuditGraphState) -> AuditGraphState:
    provider: CompanyInfoProvider = state["provider"]
    infos = {}
    for record in state["records"]:
        company_name = clean_company_name(record.company_raw)
        if company_name not in infos:
            record.company_name = company_name
            logger.info(
                "audit_query_company_start 开始查询企业 row=%s company=%s provider=%s website_url=%s",
                record.row_number,
                company_name,
                provider.__class__.__name__,
                record.website_url,
            )
            infos[company_name] = provider.get_company_info_for_record(record)
            info = infos[company_name]
            if info.success:
                logger.info(
                    "audit_query_company_success 企业信息获取成功 company=%s source=%s scope_length=%s",
                    company_name,
                    info.source,
                    len(info.business_scope or ""),
                )
            else:
                logger.warning(
                    "audit_query_company_failed 企业信息获取失败 company=%s source=%s error=%s",
                    company_name,
                    info.source,
                    info.error,
                )
    return {"company_infos": infos, "steps": state.get("steps", []) + [f"查询企业 {len(infos)} 家"]}


def match_rules_node(state: AuditGraphState) -> AuditGraphState:
    infos = state["company_infos"]
    logger.info("audit_query_company_done 企业查询完成 company_count=%s", len(infos))
    results = []
    classification_agent = build_classification_agent_from_env()
    if classification_agent:
        logger.info("classification_agent_enabled 大模型分类 Agent 已启用")
    for record in state["records"]:
        company_name = clean_company_name(record.company_raw)
        results.append(audit_record(record, state["rules"], infos.get(company_name), classification_agent=classification_agent))
    return {"results": results, "steps": state.get("steps", []) + [f"完成审计 {len(results)} 条"]}


def build_summary_node(state: AuditGraphState) -> AuditGraphState:
    status_counts: dict[str, int] = {}
    for result in state["results"]:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    logger.info(
        "audit_match_rules_done 规则匹配完成 result_count=%s status_counts=%s",
        len(state["results"]),
        status_counts,
    )
    summary = {"person_summary": build_person_summary(state["results"])}
    logger.info("audit_summary_done 质量汇总完成 person_count=%s", len(summary["person_summary"]))
    return {"summary": summary, "steps": state.get("steps", []) + ["生成质量汇总"]}


def export_result_node(state: AuditGraphState) -> AuditGraphState:
    output_dir = Path(state["output_dir"])
    job_id = state.get("job_id") or "audit_result"
    output_path = output_dir / f"{job_id}.xlsx"
    write_audit_result_excel(state["results"], output_path)
    logger.info("audit_export_done 审计结果导出完成 output_path=%s result_count=%s", output_path, len(state["results"]))
    return {"output_path": str(output_path), "steps": state.get("steps", []) + ["导出审计结果 Excel"]}
