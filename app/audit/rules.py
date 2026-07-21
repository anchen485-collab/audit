import logging
import re

from app.audit.scoring import group_rules, score_rule_group
from app.core.models import AuditResult, CategoryRule, CompanyInfo, EmployeeRecord


logger = logging.getLogger(__name__)


def clean_company_name(value: str) -> str:
    """清洗企业名称字段，去掉官网链接和多余空白。"""
    text = re.sub(r"https?://\S+|www\.\S+", "", value or "")
    text = re.sub(r"\s+", "", text)
    return text.strip("，,；;。")


def _base_result(record: EmployeeRecord, status: str, confidence: int) -> AuditResult:
    cleaned_name = clean_company_name(record.company_raw)
    return AuditResult(
        row_number=record.row_number,
        employee_name=record.name,
        original_category=record.category,
        original_subcategory=record.subcategory,
        original_stage=record.stage,
        original_company=record.company_raw,
        cleaned_company=cleaned_name,
        status=status,
        confidence=confidence,
        website_url=record.website_url,
    )


def _missing_fields(record: EmployeeRecord) -> list[str]:
    fields = {
        "日期": record.date,
        "姓名": record.name,
        "一级分类": record.category,
        "细分": record.subcategory,
        "企业名称&官网": record.company_raw,
    }
    return [name for name, value in fields.items() if not value]


def audit_record(
    record: EmployeeRecord,
    rules: list[CategoryRule],
    company: CompanyInfo | None,
    classification_agent=None,
) -> AuditResult:
    """审计单条记录：默认规则匹配；配置后可用大模型 Agent 做语义判断。"""
    record.company_name = clean_company_name(record.company_raw)
    missing = _missing_fields(record)
    if missing:
        result = _base_result(record, "信息缺失", 0)
        result.error_type = "信息缺失"
        result.reason = f"必填字段缺失：{'、'.join(missing)}"
        result.needs_review = True
        return result

    if company is None or not company.success:
        result = _base_result(record, "无法判断", 0)
        result.data_source = company.source if company else ""
        result.website_url = (company.raw.get("website_url") if company else "") or record.website_url
        result.business_scope = company.business_scope if company else ""
        result.error_type = "企业信息缺失"
        result.reason = company.error if company else "未查询到企业信息"
        result.needs_review = True
        return result

    grouped = group_rules(rules)
    business_scope = company.business_scope or ""
    current_key = None
    current_score = 0
    current_evidence: list[str] = []
    best_key = None
    best_score = 0
    best_evidence: list[str] = []

    for key, group in grouped.items():
        score, evidence = score_rule_group(group, record.category, record.subcategory, business_scope)
        if key[1] == record.category and key[2] == record.subcategory:
            current_key = key
            current_score = score
            current_evidence = evidence
        # 推荐分类只看外部证据文本，避免员工填错内容反向污染推荐结果。
        recommendation_score, recommendation_evidence = score_rule_group(group, "", "", business_scope)
        if recommendation_score > best_score:
            best_key = key
            best_score = recommendation_score
            best_evidence = recommendation_evidence

    result = _base_result(record, "无法判断", current_score)
    result.company_name = company.company_name
    result.company_status = company.status
    result.business_scope = business_scope
    result.data_source = company.source
    result.website_url = company.raw.get("website_url", record.website_url)

    if not business_scope:
        result.status = "无法判断"
        result.error_type = "外部证据缺失"
        result.reason = "外部证据文本为空，无法进行分类匹配"
        result.needs_review = True
        return result

    if classification_agent:
        try:
            agent_result = classification_agent.classify(record, company, rules)
            return _apply_agent_result(result, agent_result, grouped)
        except Exception as exc:
            logger.exception(
                "classification_agent_failed 大模型分类 Agent 调用失败 row=%s company=%s error=%s",
                record.row_number,
                record.company_name,
                exc,
            )

    if current_key and current_score >= 80:
        result.status = "正确"
        result.confidence = current_score
        result.reason = "；".join(current_evidence) or "分类和外部证据匹配"
        result.needs_review = False
        return result

    if best_key and best_score >= 35 and (not current_key or current_score < 60):
        result.status = "错误"
        result.confidence = max(best_score, 60)
        result.error_type = "细分错误"
        result.suggestion = f"{best_key[1]} / {best_key[2]}"
        result.reason = "外部证据更匹配建议分类：" + "；".join(best_evidence)
        result.needs_review = False
        return result

    result.status = "疑似错误"
    result.confidence = current_score
    result.error_type = "证据不足"
    result.reason = "外部证据与当前分类只有部分匹配，建议人工复核"
    result.needs_review = True
    return result


def _apply_agent_result(result: AuditResult, agent_result, grouped: dict[tuple[str, str, str], list[CategoryRule]]) -> AuditResult:
    matched_level1 = agent_result.matched_level1
    matched_level2 = agent_result.matched_level2
    matched_text = " / ".join(part for part in [matched_level1, matched_level2] if part)
    matched_key_exists = _level_pair_exists(grouped, matched_level1, matched_level2)
    current_key_exists = _level_pair_exists(grouped, result.original_category, result.original_subcategory)

    result.confidence = agent_result.confidence
    result.reason = f"大模型语义判断：{agent_result.reason}" if agent_result.reason else "大模型语义判断"
    result.needs_review = agent_result.needs_review

    if agent_result.audit_result == "正确":
        if not current_key_exists:
            result.status = "错误"
            result.error_type = "内部分类不存在"
            result.suggestion = _level1_level2_suggestion(agent_result.suggestion, matched_text)
            result.reason += "；员工录入的一级/二级组合未在内部分类表中精确存在，不能判为正确"
            result.needs_review = True
            return result
        if matched_text and not matched_key_exists:
            result.status = "疑似错误"
            result.error_type = "语义分类需复核"
            result.suggestion = _level1_level2_suggestion(agent_result.suggestion, matched_text)
            result.reason += "；模型返回的一级/二级组合未在内部分类表中精确存在，不能判为正确"
            result.needs_review = True
            return result
        result.status = "正确"
        result.error_type = ""
        result.suggestion = ""
        return result

    if agent_result.audit_result == "错误":
        result.status = "错误"
        result.error_type = "语义分类不匹配"
        result.suggestion = _level1_level2_suggestion(agent_result.suggestion, matched_text)
        if matched_text and not matched_key_exists:
            result.status = "疑似错误"
            result.error_type = "语义分类需复核"
            result.reason += "；模型返回的建议分类未在内部分类表中精确命中，需要人工复核"
            result.needs_review = True
        return result

    if agent_result.audit_result == "无法判断":
        result.status = "无法判断"
        result.error_type = "语义无法判断"
        result.suggestion = _level1_level2_suggestion(agent_result.suggestion, matched_text)
        result.needs_review = True
        return result

    result.status = "疑似错误"
    result.error_type = "语义证据不足"
    result.suggestion = _level1_level2_suggestion(agent_result.suggestion, matched_text)
    result.needs_review = True
    return result


def _level_pair_exists(grouped: dict[tuple[str, str, str], list[CategoryRule]], level1: str, level2: str) -> bool:
    return any(key[0] == level1 and key[1] == level2 for key in grouped)


def _level1_level2_suggestion(suggestion: str, fallback: str = "") -> str:
    value = (suggestion or fallback or "").strip()
    if not value:
        return ""

    fallback_parts = _split_suggestion_parts(fallback)
    labeled_level1 = _extract_labeled_suggestion(value, "一级")
    labeled_level2 = _extract_labeled_suggestion(value, "二级")
    if labeled_level1 or labeled_level2:
        level1 = labeled_level1 or (fallback_parts[0] if fallback_parts else "")
        level2 = labeled_level2 or (fallback_parts[1] if len(fallback_parts) > 1 else "")
        return " / ".join(part for part in [level1, level2] if part)

    normalized = value.replace("／", "/").replace("\\", "/")
    normalized = re.sub(r"(?:[/，,；;（(]\s*)?(?:三级|三级分类|三级品类)\s*[:：=].*$", "", normalized)
    normalized = re.sub(r"\s*/\s*", " / ", normalized)
    normalized = re.sub(r"(?:一级|一级分类|一级品类)\s*[:：=]\s*", "", normalized)
    normalized = re.sub(r"(?:二级|二级分类|二级品类)\s*[:：=]\s*", "", normalized)
    parts = _split_suggestion_parts(normalized)
    if len(parts) >= 2:
        return " / ".join(parts[:2])
    return " / ".join(parts) if parts else normalized.strip()


def _extract_labeled_suggestion(value: str, label: str) -> str:
    pattern = rf"{label}(?:分类|品类)?\s*[:：=]\s*([^/，,；;）)\n]+)"
    match = re.search(pattern, value)
    if not match:
        return ""
    return match.group(1).strip(" '\"“”‘’")


def _split_suggestion_parts(value: str) -> list[str]:
    normalized = (value or "").replace("／", "/").replace("\\", "/")
    return [part.strip(" '\"“”‘’") for part in normalized.split("/") if part.strip(" '\"“”‘’")]
