import logging
import os
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
        if _matches_entered_category_path(key, record.category, record.subcategory) and score > current_score:
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
            candidate_rules = _candidate_rules_for_agent(
                rules,
                grouped,
                record,
                business_scope,
                getattr(classification_agent, "candidate_topk", None),
                getattr(classification_agent, "entered_level1_expand_topk", None),
                getattr(classification_agent, "evidence_topk", None),
            )
            logger.info(
                "classification_agent_candidates row=%s company=%s topk=%s candidate_rules=%s total_rules=%s",
                record.row_number,
                record.company_name,
                getattr(classification_agent, "candidate_topk", None),
                len(candidate_rules),
                len(rules),
            )
            agent_result = classification_agent.classify(record, company, candidate_rules)
            return _apply_agent_result(result, agent_result, grouped)
        except Exception as exc:
            logger.exception(
                "classification_agent_failed 大模型分类 Agent 调用失败 row=%s company=%s error=%s",
                record.row_number,
                record.company_name,
                exc,
            )

    contained_categories = _contained_entered_categories(record, business_scope)
    if current_key and contained_categories:
        result.status = "正确"
        result.confidence = max(current_score, 70)
        result.error_type = "补充信息提示"
        result.reason = (
            f"官网证据包含员工录入分类：{'、'.join(contained_categories)}；"
            "官网证据可能同时覆盖其他业务方向，建议补充企业主营信息或人工确认"
        )
        result.needs_review = True
        return result

    if current_key and current_score >= 80:
        result.status = "正确"
        result.confidence = current_score
        result.reason = "；".join(current_evidence) or "分类和外部证据匹配"
        result.needs_review = False
        return result

    if current_key and current_score >= 60 and _has_business_keyword_evidence(current_evidence):
        result.status = "正确"
        result.confidence = current_score
        result.error_type = "低置信度匹配"
        result.reason = (
            "分类和外部证据部分匹配："
            + ("；".join(current_evidence) or "当前分类命中")
            + "；置信度未达到高可信阈值，建议人工复核"
        )
        result.needs_review = True
        return result

    if best_key and best_score >= 35 and (not current_key or current_score < 60):
        result.status = "错误"
        result.confidence = max(best_score, 60)
        result.error_type = "细分错误"
        result.suggestion = _suggestion_if_changed(result, f"{best_key[1]} / {best_key[2]}")
        result.reason = "外部证据更匹配建议分类：" + "；".join(best_evidence)
        result.needs_review = False
        return result

    result.status = "疑似错误"
    result.confidence = current_score
    result.error_type = "证据不足"
    result.reason = "外部证据与当前分类只有部分匹配，建议人工复核"
    result.needs_review = True
    return result


def _contained_entered_categories(record: EmployeeRecord, business_scope: str) -> list[str]:
    """判断官网证据是否直接包含员工录入的分类名称。"""
    if not record.subcategory:
        return []
    entered_categories = [record.category, *_split_category_values(record.subcategory)]
    return [name for name in entered_categories if name and name in business_scope]


def _split_category_values(value: str) -> list[str]:
    """把员工单元格中的多个细分拆开，兼容常见分隔符。"""
    return [part.strip() for part in re.split(r"[、，,;；/\\\n\r]+", value or "") if part.strip()]


def _has_business_keyword_evidence(evidence: list[str]) -> bool:
    """判断当前分类是否有外部经营/官网关键词支持。"""
    return any(item.startswith("经营范围关键词：") for item in evidence)


def _matches_entered_category_path(key: tuple[str, str, str], category: str, subcategory: str) -> bool:
    """判断员工录入的一级分类和细分是否命中内部分类路径。"""
    level1, level2, level3 = key
    subcategories = _split_category_values(subcategory)
    if not subcategories:
        return False
    return any(
        (category == level1 and item in {level2, level3})
        # 兼容历史数据：旧模板里“一级分类”可能实际填写的是内部二级品类。
        or (category == level2 and item == level3)
        for item in subcategories
    )


def _entered_category_path_exists(grouped: dict[tuple[str, str, str], list[CategoryRule]], category: str, subcategory: str) -> bool:
    """判断员工录入分类是否存在于内部分类表任一层级路径中。"""
    subcategories = _split_category_values(subcategory)
    if not subcategories:
        return False
    return all(any(_matches_entered_category_path(key, category, item) for key in grouped) for item in subcategories)


def _agent_category_path_exists(
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    level1: str,
    level2: str,
    level3: str = "",
) -> bool:
    """判断大模型返回的内部分类路径是否存在。"""
    if level3:
        level3_values = _split_category_values(level3)
        return all(any(key == (level1, level2, item) for key in grouped) for item in level3_values)
    level2_values = _split_category_values(level2)
    if not level2_values:
        return False
    return all(any(key[0] == level1 and key[1] == item for key in grouped) for item in level2_values)


def _candidate_rules_for_agent(
    rules: list[CategoryRule],
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    record: EmployeeRecord,
    business_scope: str,
    top_k: int | None = None,
    entered_level1_expand_topk: int | None = None,
    evidence_topk: int | None = None,
) -> list[CategoryRule]:
    if top_k is None:
        top_k = int(os.getenv("AUDIT_LLM_CANDIDATE_TOPK", "30"))
    if entered_level1_expand_topk is None:
        entered_level1_expand_topk = int(os.getenv("AUDIT_LLM_ENTERED_LEVEL1_EXPAND_TOPK", "10"))
    if evidence_topk is None:
        evidence_topk = int(os.getenv("AUDIT_LLM_EVIDENCE_TOPK", "20"))
    if top_k <= 0 or not grouped:
        return rules

    scored_keys: list[tuple[int, int, tuple[str, str, str]]] = []
    for index, (key, group) in enumerate(grouped.items()):
        evidence_score, _ = score_rule_group(group, "", "", business_scope)
        entered_score, _ = score_rule_group(group, record.category, record.subcategory, business_scope)
        path_boost = 40 if _matches_entered_category_path(key, record.category, record.subcategory) else 0
        text_boost = sum(8 for level in key if level and level in business_scope)
        scored_keys.append((evidence_score + entered_score + path_boost + text_boost, -index, key))

    ranked_keys = sorted(scored_keys, key=lambda item: (item[0], item[1]), reverse=True)
    selected_keys: list[tuple[str, str, str]] = []
    _extend_unique_keys(selected_keys, _entered_exact_candidate_keys(grouped, record))
    _extend_unique_keys(
        selected_keys,
        _ranked_entered_level_candidates(ranked_keys, record, entered_level1_expand_topk),
    )
    _extend_unique_keys(selected_keys, [key for score, _index, key in ranked_keys if score > 0][:evidence_topk])
    if not selected_keys:
        _extend_unique_keys(selected_keys, [key for _score, _index, key in ranked_keys[:top_k]])
    if len(selected_keys) > top_k:
        mandatory_keys = _entered_exact_candidate_keys(grouped, record)
        trimmed_keys: list[tuple[str, str, str]] = []
        _extend_unique_keys(trimmed_keys, mandatory_keys)
        remaining = max(top_k - len(trimmed_keys), 0)
        _extend_unique_keys(trimmed_keys, [key for key in selected_keys if key not in set(mandatory_keys)][:remaining])
        selected_keys = trimmed_keys

    candidate_rules: list[CategoryRule] = []
    selected_key_set = set(selected_keys)
    for key, group in grouped.items():
        if key in selected_key_set:
            candidate_rules.extend(group)
    return candidate_rules or rules


def _entered_exact_candidate_keys(
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    record: EmployeeRecord,
) -> list[tuple[str, str, str]]:
    return [
        key
        for key in grouped
        if _matches_entered_category_path(key, record.category, record.subcategory)
        or bool(record.subcategory and record.subcategory in key)
    ]


def _ranked_entered_level_candidates(
    ranked_keys: list[tuple[int, int, tuple[str, str, str]]],
    record: EmployeeRecord,
    limit: int,
) -> list[tuple[str, str, str]]:
    if limit <= 0:
        return []
    return [
        key
        for _score, _index, key in ranked_keys
        if _key_matches_entered_primary_category(key, record)
    ][:limit]


def _key_matches_entered_primary_category(key: tuple[str, str, str], record: EmployeeRecord) -> bool:
    return bool(record.category and record.category in {key[0], key[1]})


def _extend_unique_keys(target: list[tuple[str, str, str]], keys: list[tuple[str, str, str]]) -> None:
    seen = set(target)
    for key in keys:
        if key not in seen:
            target.append(key)
            seen.add(key)


def _apply_agent_result(result: AuditResult, agent_result, grouped: dict[tuple[str, str, str], list[CategoryRule]]) -> AuditResult:
    matched_level1 = agent_result.matched_level1
    matched_level2 = agent_result.matched_level2
    matched_level3 = getattr(agent_result, "matched_level3", "")
    matched_text = " / ".join(part for part in [matched_level1, matched_level2, matched_level3] if part)
    matched_key_exists = _agent_category_path_exists(grouped, matched_level1, matched_level2, matched_level3)
    current_key_exists = _entered_category_path_exists(grouped, result.original_category, result.original_subcategory)

    result.confidence = agent_result.confidence
    result.reason = f"大模型语义判断：{agent_result.reason}" if agent_result.reason else "大模型语义判断"
    result.needs_review = agent_result.needs_review

    if agent_result.audit_result == "正确":
        if not current_key_exists:
            result.status = "错误"
            result.error_type = "内部分类不存在"
            result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
            result.reason += "；员工录入的一级/二级组合未在内部分类表中精确存在，不能判为正确"
            result.needs_review = True
            return result
        if matched_text and not matched_key_exists:
            result.status = "疑似错误"
            result.error_type = "语义分类需复核"
            result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
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
        result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
        if matched_text and not matched_key_exists:
            result.status = "疑似错误"
            result.error_type = "语义分类需复核"
            result.reason += "；模型返回的建议分类未在内部分类表中精确命中，需要人工复核"
            result.needs_review = True
        return result

    if agent_result.audit_result == "无法判断":
        result.status = "无法判断"
        result.error_type = "语义无法判断"
        result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
        result.needs_review = True
        return result

    result.status = "疑似错误"
    result.error_type = "语义证据不足"
    result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
    result.needs_review = True
    return result


def _suggestion_if_changed(result: AuditResult, suggestion: str) -> str:
    """只有建议分类不同于员工原录入时才展示。"""
    value = (suggestion or "").strip()
    if not value:
        return ""
    if _normalize_category_path(value) == _normalize_category_path(f"{result.original_category} / {result.original_subcategory}"):
        return ""
    return value


def _normalize_category_path(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("／", "/").replace("\\", "/")
    value = value.replace("，", ",").replace("、", ",")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"/+", "/", value)
    return value.strip("/")


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
