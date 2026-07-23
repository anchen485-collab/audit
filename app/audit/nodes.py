import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.agent import build_classification_agent_from_env
from app.audit.rules import audit_record, clean_company_name
from app.audit.summary import build_person_summary
from app.category.rule_index import load_category_rules_from_config
from app.company.provider import CompanyInfoProvider
from app.core.models import AuditGraphState
from app.core.trace import elapsed_ms
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
            query_start = perf_counter()
            infos[company_name] = provider.get_company_info_for_record(record)
            info = infos[company_name]
            query_duration_ms = elapsed_ms(query_start)
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
            logger.info(
                "audit_query_company_timing 企业查询耗时 row=%s company=%s provider=%s success=%s duration_ms=%.2f",
                record.row_number,
                company_name,
                provider.__class__.__name__,
                info.success,
                query_duration_ms,
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


def pipeline_audit_node(state: AuditGraphState) -> AuditGraphState:
    """流水线审计节点：先串行爬取所有企业，再用 ThreadPoolExecutor 并发调用 AI 审计。

    相比原来的 query_company_node + match_rules_node 两个串行节点，
    此节点在审计阶段使用多线程并发，显著减少总耗时。
    """
    provider: CompanyInfoProvider = state["provider"]
    records = state["records"]
    rules = state["rules"]
    classification_agent = build_classification_agent_from_env()
    if classification_agent:
        logger.info("classification_agent_enabled 大模型分类 Agent 已启用")

    pipeline_start = perf_counter()
    infos: dict[str, object] = {}
    crawl_phase_ms = 0.0

    # 阶段一：串行爬取（爬虫本身有网络 I/O，串行即可）
    for record in records:
        company_name = clean_company_name(record.company_raw)
        if company_name in infos:
            continue
        record.company_name = company_name
        logger.info(
            "pipeline_crawl_start 开始爬取企业 row=%s company=%s url=%s",
            record.row_number, company_name, record.website_url,
        )
        crawl_start = perf_counter()
        infos[company_name] = provider.get_company_info_for_record(record)
        crawl_duration = elapsed_ms(crawl_start)
        info = infos[company_name]
        logger.info(
            "pipeline_crawl_done 企业爬取完成 row=%s company=%s success=%s duration_ms=%.2f",
            record.row_number, company_name, info.success, crawl_duration,
        )

    crawl_phase_ms = elapsed_ms(pipeline_start)

    # 阶段二：并发审计
    if not classification_agent:
        # 无 AI 时串行审计（关键词匹配很快，不需要并发）
        results = []
        for record in records:
            company_name = clean_company_name(record.company_raw)
            results.append(audit_record(record, rules, infos.get(company_name)))
        audit_phase_ms = elapsed_ms(pipeline_start) - crawl_phase_ms
    else:
        max_workers = min(len(records), int(os.environ.get("WEBSITE_CRAWL_CONCURRENCY", "5")))
        logger.info(
            "pipeline_audit_concurrent_start 并发 AI 审计开始 total_count=%s max_workers=%s",
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
            logger.info("pipeline_audit_start 开始审计 row=%s company=%s", record.row_number, company_name)
            result = audit_record(record, rules, info, classification_agent=classification_agent)
            t = elapsed_ms(t0)
            with stats_lock:
                audit_times.append(t)
            with results_lock:
                results[record_idx] = result
            logger.info(
                "pipeline_audit_done 审计完成 row=%s company=%s status=%s duration_ms=%.2f",
                record.row_number, company_name, result.status, t,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(audit_one, i, rec): i for i, rec in enumerate(records)}
            for future in as_completed(futures):
                future.result()  # 确保异常被抛出

        audit_phase_ms = elapsed_ms(pipeline_start) - crawl_phase_ms
        logger.info(
            "pipeline_audit_concurrent_done 并发 AI 审计完成 count=%s "
            "avg_audit_ms=%.1f max_audit_ms=%.1f",
            len(results),
            sum(audit_times) / len(audit_times) if audit_times else 0,
            max(audit_times) if audit_times else 0,
        )

    total_ms = elapsed_ms(pipeline_start)
    logger.info(
        "pipeline_audit_summary 流水线审计耗时汇总 total_count=%s "
        "流水线总耗时=%.2fms 爬虫阶段=%.2fms 审计阶段=%.2fms",
        len(records), total_ms, crawl_phase_ms, audit_phase_ms,
    )
    return {"results": results, "company_infos": infos, "steps": state.get("steps", []) + [f"流水线审计 {len(results)} 条"]}


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
