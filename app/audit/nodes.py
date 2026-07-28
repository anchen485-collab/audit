import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.agents import build_classification_agent_from_env
from app.audit.rules import audit_record, clean_company_name
from app.audit.summary import build_person_summary
from app.categories.rule_index import load_category_rules_from_config
from app.companies.providers.base import CompanyInfoProvider
from app.core.models import AuditGraphState
from app.core.trace import elapsed_ms
from app.documents.excel.input_reader import read_employee_excel
from app.documents.excel.result_writer import write_audit_result_excel


logger = logging.getLogger(__name__)


def _configured_worker_count(total: int, env_name: str, default: int) -> int:
    if total <= 0:
        return 0
    try:
        configured = int(os.environ.get(env_name, str(default)))
    except ValueError:
        logger.warning("audit_invalid_concurrency 并发配置不是整数 env=%s value=%s", env_name, os.environ.get(env_name))
        configured = default
    return min(total, max(configured, 1))


def read_employee_node(state: AuditGraphState) -> AuditGraphState:
    records = read_employee_excel(state["employee_file"])
    logger.info("audit_read_employee_done 员工录入读取完成 file=%s record_count=%s", state["employee_file"], len(records))
    return {"records": records, "steps": state.get("steps", []) + [f"读取员工记录 {len(records)} 条"]}


def read_category_node(state: AuditGraphState) -> AuditGraphState:
    category_source = state.get("category_file")
    rules = load_category_rules_from_config(category_source)
    logger.info("audit_read_category_done 分类规则读取完成 source=%s rule_count=%s", category_source or "configured_json", len(rules))
    return {"rules": rules, "steps": state.get("steps", []) + [f"读取分类规则 {len(rules)} 条"]}


def query_company_info_node(state: AuditGraphState) -> AuditGraphState:
    """并发获取去重后的企业信息。"""
    provider: CompanyInfoProvider = state["provider"]
    records = state["records"]
    infos: dict[str, object] = {}

    if not records:
        logger.info("query_company_info_empty 员工记录为空，跳过企业查询")
        return {"company_infos": infos, "steps": state.get("steps", []) + ["查询企业 0 家"]}

    unique_records: dict[str, object] = {}
    for record in records:
        company_name = clean_company_name(record.company_raw)
        record.company_name = company_name
        unique_records.setdefault(company_name, record)

    node_start = perf_counter()
    max_workers = _configured_worker_count(len(unique_records), "WEBSITE_CRAWL_CONCURRENCY", 5)
    infos_lock = Lock()
    logger.info(
        "query_company_info_concurrent_start 并发查询企业开始 total_count=%s unique_company_count=%s max_workers=%s",
        len(records),
        len(unique_records),
        max_workers,
    )

    def query_one(company_name: str, record: object) -> None:
        logger.info(
            "query_company_info_start 开始查询企业 row=%s company=%s provider=%s website_url=%s thread=%s",
            record.row_number,
            company_name,
            provider.__class__.__name__,
            record.website_url,
            threading.current_thread().name,
        )
        query_start = perf_counter()
        info = provider.get_company_info_for_record(record)
        query_duration_ms = elapsed_ms(query_start)
        with infos_lock:
            infos[company_name] = info
        if info.success:
            logger.info(
                "query_company_info_success 企业信息获取成功 company=%s source=%s scope_length=%s",
                company_name,
                info.source,
                len(info.business_scope or ""),
            )
        else:
            logger.warning(
                "query_company_info_failed 企业信息获取失败 company=%s source=%s error=%s",
                company_name,
                info.source,
                info.error,
            )
        logger.info(
            "audit_query_company_timing 企业查询耗时 row=%s company=%s provider=%s success=%s duration_ms=%.2f",
            record.row_number,
            company_name,
            provider.__class__.__name__,
            info.success,
            query_duration_ms,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_one, company_name, record): company_name for company_name, record in unique_records.items()}
        for future in as_completed(futures):
            future.result()  # 确保异常被抛出

    logger.info(
        "query_company_info_concurrent_done 并发查询企业完成 total_count=%s unique_company_count=%s duration_ms=%.2f",
        len(records),
        len(infos),
        elapsed_ms(node_start),
    )
    return {"company_infos": infos, "steps": state.get("steps", []) + [f"查询企业 {len(infos)} 家"]}


def audit_records_node(state: AuditGraphState) -> AuditGraphState:
    """基于已查询的企业信息执行规则审计和可选 LLM 审计。"""
    records = state["records"]
    rules = state["rules"]
    infos = state.get("company_infos", {})
    classification_agent = build_classification_agent_from_env()
    if classification_agent:
        logger.info("classification_agent_enabled 大模型分类 Agent 已启用")

    node_start = perf_counter()
    if not records:
        logger.info("audit_records_empty 员工记录为空，跳过审计")
        return {"results": [], "steps": state.get("steps", []) + ["完成审计 0 条"]}

    if not classification_agent:
        results = []
        for record in records:
            company_name = clean_company_name(record.company_raw)
            results.append(audit_record(record, rules, infos.get(company_name)))
    else:
        max_workers = _configured_worker_count(len(records), "AUDIT_LLM_CONCURRENCY", 4)
        logger.info(
            "audit_records_concurrent_start 并发 AI 审计开始 total_count=%s max_workers=%s",
            len(records), max_workers,
        )
        results: list = [None] * len(records)
        results_lock = Lock()
        audit_times: list[float] = []
        stats_lock = Lock()

        def audit_one(record_idx: int, record: object) -> None:
            company_name = clean_company_name(record.company_raw)
            info = infos.get(company_name)
            t0 = perf_counter()
            logger.info("audit_records_start 开始审计 row=%s company=%s thread=%s", record.row_number, company_name, threading.current_thread().name)
            result = audit_record(record, rules, info, classification_agent=classification_agent)
            t = elapsed_ms(t0)
            with stats_lock:
                audit_times.append(t)
            with results_lock:
                results[record_idx] = result
            logger.info(
                "audit_records_done 审计完成 row=%s company=%s status=%s duration_ms=%.2f thread=%s",
                record.row_number, company_name, result.status, t, threading.current_thread().name,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(audit_one, i, rec): i for i, rec in enumerate(records)}
            for future in as_completed(futures):
                future.result()  # 确保异常被抛出

        logger.info(
            "audit_records_concurrent_done 并发 AI 审计完成 count=%s "
            "avg_audit_ms=%.1f max_audit_ms=%.1f",
            len(results),
            sum(audit_times) / len(audit_times) if audit_times else 0,
            max(audit_times) if audit_times else 0,
        )

    logger.info(
        "audit_records_summary 审计耗时汇总 total_count=%s duration_ms=%.2f",
        len(records),
        elapsed_ms(node_start),
    )
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
