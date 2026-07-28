import logging
import os
import re

from app.audit.scoring import group_rules, score_rule_group
from app.audit.rule_constants import (
    AGRI_EQUIPMENT_DOMAIN_WORDS,
    CONSULTING_CONTEXT_WORDS,
    CONSULTING_PRIMARY_WORDS,
    ENGINEERING_CONTEXT_WORDS,
    ENGINEERING_DOMAIN_TARGETS,
    EQUIPMENT_CONTEXT_WORDS,
    EQUIPMENT_DOMAIN_TARGETS,
    EVIDENCE_ALIASES,
    EXHIBITION_CONTEXT_WORDS,
    EXHIBITION_DOMAIN_TARGETS,
    FERTILIZER_STRONG_WORDS,
    FERTILIZER_WEAK_WORDS,
    FULL_CATEGORY_REVIEW_TRIGGER_WORDS,
    GENERIC_RETRIEVAL_WORDS,
    LIVESTOCK_SUBCATEGORY_MAP,
    LOW_SIGNAL_RETRIEVAL_MODULES,
    MATERIAL_CONTEXT_WORDS,
    MATERIAL_DOMAIN_TARGETS,
    PRODUCT_PRIMARY_WORDS,
    SOFTWARE_CONTEXT_WORDS,
    SOFTWARE_PRIMARY_WORDS,
    UNUSABLE_EXTERNAL_EVIDENCE_PATTERNS,
)
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
        recommendation_score, recommendation_evidence = score_rule_group(group, "", "", business_scope)
        recommendation_score += _alias_score_for_key(key, business_scope)
        if recommendation_score > best_score:
            best_key = key
            best_score = recommendation_score
            best_evidence = recommendation_evidence or _alias_evidence_for_key(key, business_scope)

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
            if _needs_full_category_review(agent_result) or _has_invalid_agent_category_path(agent_result, grouped):
                logger.info(
                    "classification_agent_full_review row=%s company=%s reason=%s",
                    record.row_number,
                    record.company_name,
                    agent_result.reason,
                )
                agent_result = _classify_with_full_category_table(classification_agent, record, company, rules)
                agent_result = _normalize_full_review_agent_result(agent_result, best_key, best_score)
                agent_result.reason = (
                    f"已触发全量分类表复核：{agent_result.reason}"
                    if agent_result.reason
                    else "已触发全量分类表复核"
                )
            return _apply_agent_result(result, agent_result, grouped, best_key, best_score)
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

    if current_key and current_score >= 70:
        result.status = "正确"
        result.confidence = current_score
        result.reason = "；".join(current_evidence) or "分类和外部证据匹配"
        result.needs_review = False
        return result

    if current_key and current_score >= 50 and _has_business_keyword_evidence(current_evidence):
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

    if best_key and best_score >= 35 and (not current_key or current_score < 50):
        result.status = "错误"
        result.confidence = max(best_score, 60)
        result.error_type = "细分错误"
        result.suggestion = _suggestion_if_changed(result, f"{best_key[1]} / {best_key[2]}")
        result.reason = "外部证据更匹配建议分类：" + "；".join(best_evidence)
        result.needs_review = False
        return result

    if _looks_latin_language_evidence(business_scope):
        result.status = "无法判断"
        result.confidence = current_score
        result.error_type = "外文证据需语义复核"
        result.reason = "外部证据文本主要为英文/外文，规则关键词无法充分命中当前中文分类；需要大模型语义判断或人工复核"
        result.needs_review = True
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


def _looks_latin_language_evidence(text: str) -> bool:
    """识别以英文/西语等拉丁文字为主的官网证据，避免中文关键词兜底误判。"""
    if not text:
        return False
    latin_letter_count = sum(
        1
        for char in text
        if ("A" <= char <= "Z") or ("a" <= char <= "z") or ("\u00c0" <= char <= "\u024f")
    )
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin_words = re.findall(r"[A-Za-zÀ-ɏ]{3,}", text)
    return latin_letter_count >= 40 and len(latin_words) >= 6 and latin_letter_count > cjk_count * 4


def _is_generic_partial_match_reason(text: str) -> bool:
    """识别大模型/兜底返回的泛化部分匹配原因。"""
    return any(
        phrase in (text or "")
        for phrase in [
            "外部证据与当前分类只有部分匹配",
            "外部证据与当前分类部分匹配",
            "只有部分匹配，建议人工复核",
            "部分匹配，建议人工复核",
        ]
    )


def _rewrite_generic_foreign_language_reason(result: AuditResult) -> None:
    """外文证据下不要透传“部分匹配”这种无信息量结论。"""
    if not _looks_latin_language_evidence(result.business_scope):
        return
    if not _is_generic_partial_match_reason(result.reason):
        return
    result.error_type = "外文证据需语义复核"
    result.reason = (
        "大模型语义判断：外部证据文本主要为英文/外文，当前返回结果未给出足够具体的语义匹配依据；"
        "请结合外文证据语义复核当前分类"
    )
    result.needs_review = True


# 一级分类名称别名映射（员工惯用简称 → 内部分类表正式名称）
_CATEGORY_ALIAS_MAP: dict[str, str] = {
    "房建": "房屋建筑",
}


def _normalize_category_values(values: list[str]) -> list[str]:
    """将员工录入的一级分类别名标准化为内部分类表正式名称。"""
    return [_CATEGORY_ALIAS_MAP.get(v, v) for v in values]



def _matches_entered_category_path(key: tuple[str, str, str], category: str, subcategory: str) -> bool:
    """判断员工录入的一级分类和细分是否命中内部分类路径。

    一级分类支持别名映射（如"房建"→"房屋建筑"）；
    当一级分类为"畜牧业"时，启用细分名称等价映射（如"家禽"↔"家禽养殖"）。
    """
    level1, level2, level3 = key
    subcategories = _split_category_values(subcategory)
    categories = _normalize_category_values(_split_category_values(category))
    if not subcategories or not categories:
        return False

    # 判断当前内部分类路径的一级是否为畜牧业
    is_livestock = level1 == "畜牧业"

    def _subcategory_matches(item: str, target: str) -> bool:
        """判断员工细分 item 是否匹配内部分类路径中的 target（二级或三级）。"""
        if item == target:
            return True
        if is_livestock:
            # 畜牧业下启用等价映射
            equivalents = LIVESTOCK_SUBCATEGORY_MAP.get(item, set())
            return target in equivalents
        return False

    return any(
        (cat == level1 and _subcategory_matches(item, level2))
        or (cat == level1 and _subcategory_matches(item, level3))
        or (cat == level2 and item == level3)
        or (cat == level1 and level2 == cat and item == level3)
        for item in subcategories
        for cat in categories
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
    """判断大模型返回的内部分类路径是否存在。

    level1 和 level2 均支持逗号分隔的多个值，只要任一 level1 与 level2 的组合存在即视为匹配。
    """
    level1_values = _split_category_values(level1)
    level2_values = _split_category_values(level2)
    if not level1_values or not level2_values:
        return False
    if level3:
        level3_values = _split_category_values(level3)
        return all(
            any(key == (l1, l2, item) for key in grouped for l1 in level1_values for l2 in level2_values)
            for item in level3_values
        )
    # level2 可能包含多个值（逗号分隔），每个值都需存在
    return all(
        any(key[0] == l1 and key[1] == l2 for key in grouped for l1 in level1_values)
        for l2 in level2_values
    )


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
        top_k = int(os.getenv("AUDIT_LLM_CANDIDATE_TOPK", "80"))
    if entered_level1_expand_topk is None:
        entered_level1_expand_topk = int(os.getenv("AUDIT_LLM_ENTERED_LEVEL1_EXPAND_TOPK", "0"))
    if evidence_topk is None:
        evidence_topk = int(os.getenv("AUDIT_LLM_EVIDENCE_TOPK", "60"))
    if top_k <= 0 or not grouped:
        return rules

    ranked_keys = _rank_candidate_keys(grouped, record, business_scope)
    selected_keys: list[tuple[str, str, str]] = []
    evidence_limit = min(max(evidence_topk, 0), top_k)
    evidence_keys = [key for score, _index, key in ranked_keys if score > 0][:evidence_limit]
    _extend_unique_keys(selected_keys, evidence_keys, limit=top_k)

    exact_keys = _entered_exact_candidate_keys(grouped, record, business_scope)
    exact_limit = max(0, min(len(exact_keys), top_k - len(selected_keys)))
    _extend_unique_keys(selected_keys, exact_keys[:exact_limit], limit=top_k)

    entered_level_keys = _ranked_entered_level_candidates(ranked_keys, record, entered_level1_expand_topk)
    _extend_unique_keys(selected_keys, entered_level_keys, limit=top_k)

    if not selected_keys:
        _extend_unique_keys(selected_keys, [key for _score, _index, key in ranked_keys], limit=top_k)

    candidate_rules: list[CategoryRule] = []
    for key in selected_keys:
        candidate_rules.extend(grouped.get(key, []))
    return candidate_rules or rules


def _needs_full_category_review(agent_result) -> bool:
    matched_keywords = getattr(agent_result, "matched_keywords", None) or []
    parts = [
        getattr(agent_result, "audit_result", ""),
        getattr(agent_result, "reason", ""),
        getattr(agent_result, "suggestion", ""),
        getattr(agent_result, "matched_level1", ""),
        getattr(agent_result, "matched_level2", ""),
        getattr(agent_result, "matched_level3", ""),
        getattr(agent_result, "matched_module", ""),
        " ".join(str(keyword) for keyword in matched_keywords),
    ]
    text = " ".join(part for part in parts if part)
    if any(word in text for word in FULL_CATEGORY_REVIEW_TRIGGER_WORDS):
        return True
    return bool(
        re.search(r"内部分类表.{0,6}(?:无|没有|不存在|缺少|未找到)", text)
        or re.search(r"(?:候选|子集).{0,20}(?:召回|未包含|不包含|不足|仅包含)", text)
        or re.search(r"召回.{0,20}不足", text)
        or re.search(r"未召回", text)
    )


def _has_invalid_agent_category_path(
    agent_result,
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
) -> bool:
    matched_level1 = getattr(agent_result, "matched_level1", "")
    matched_level2 = getattr(agent_result, "matched_level2", "")
    matched_level3 = getattr(agent_result, "matched_level3", "")
    if not matched_level1 or not matched_level2:
        return False
    return not _agent_category_path_exists(grouped, matched_level1, matched_level2, matched_level3)


def _classify_with_full_category_table(
    classification_agent,
    record: EmployeeRecord,
    company: CompanyInfo,
    rules: list[CategoryRule],
):
    max_chars = int(os.getenv("AUDIT_LLM_FULL_REVIEW_MAX_CATEGORY_CHARS", "80000"))
    sentinel = object()
    previous_max_chars = getattr(classification_agent, "max_category_chars", sentinel)
    previous_full_review = getattr(classification_agent, "full_category_review", sentinel)
    if previous_max_chars is sentinel:
        return classification_agent.classify(record, company, rules)
    try:
        classification_agent.max_category_chars = max_chars
        classification_agent.full_category_review = True
        return classification_agent.classify(record, company, rules)
    finally:
        classification_agent.max_category_chars = previous_max_chars
        if previous_full_review is sentinel:
            try:
                delattr(classification_agent, "full_category_review")
            except AttributeError:
                pass
        else:
            classification_agent.full_category_review = previous_full_review


def _normalize_full_review_agent_result(agent_result, fallback_key: tuple[str, str, str] | None, fallback_score: int):
    if getattr(agent_result, "audit_result", "") != "疑似错误":
        return agent_result
    text = " ".join(
        part
        for part in [
            getattr(agent_result, "reason", ""),
            getattr(agent_result, "suggestion", ""),
            getattr(agent_result, "matched_level1", ""),
            getattr(agent_result, "matched_level2", ""),
            getattr(agent_result, "matched_level3", ""),
        ]
        if part
    )
    has_clear_alternative = any(word in text for word in ["更符合企业实际", "更匹配企业实际", "更符合", "明显支持"])
    has_entered_mismatch = any(word in text for word in ["未涉及", "不涉及", "并非", "而非", "不符", "与公司实际业务不符"])
    if not (fallback_key and fallback_score >= 35 and has_clear_alternative and has_entered_mismatch):
        return agent_result
    agent_result.audit_result = "错误"
    agent_result.confidence = max(getattr(agent_result, "confidence", 0), 80)
    agent_result.needs_review = False
    if not getattr(agent_result, "suggestion", ""):
        agent_result.suggestion = f"{fallback_key[0]} / {fallback_key[1]} / {fallback_key[2]}"
    return agent_result


def _rank_candidate_keys(
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    record: EmployeeRecord,
    business_scope: str,
) -> list[tuple[int, int, tuple[str, str, str]]]:
    scored_keys: list[tuple[int, int, tuple[str, str, str]]] = []
    for index, (key, group) in enumerate(grouped.items()):
        evidence_score, _ = score_rule_group(group, "", "", business_scope)
        retrieval_score = _retrieval_keyword_score(group, business_scope)
        alias_score = _alias_score_for_key(key, business_scope)
        entered_text_score = _entered_text_support_score(key, record, business_scope)
        text_boost = sum(8 for level in key if level and level in business_scope)
        score = evidence_score + retrieval_score + alias_score + entered_text_score + text_boost
        scored_keys.append((score, -index, key))
    return sorted(scored_keys, key=lambda item: (item[0], item[1]), reverse=True)


def _retrieval_keyword_score(group: list[CategoryRule], business_scope: str) -> int:
    score = 0
    for rule in group:
        for keyword in rule.keywords:
            if not keyword or keyword not in business_scope:
                continue
            if rule.module_name in LOW_SIGNAL_RETRIEVAL_MODULES and keyword in GENERIC_RETRIEVAL_WORDS:
                continue
            score += 16 if rule.module_name not in LOW_SIGNAL_RETRIEVAL_MODULES else 6
    return min(score, 64)


def _alias_score_for_key(key: tuple[str, str, str], business_scope: str) -> int:
    if not business_scope:
        return 0
    score = 0
    if _key_matches_fertilizer_path(key):
        score += _fertilizer_alias_score(business_scope)
    equipment_target = _equipment_target_for_key(key)
    if equipment_target:
        score += _equipment_alias_score(equipment_target, business_scope)
    if _key_matches_consulting_path(key):
        score += _consulting_alias_score(business_scope)
    if _key_matches_software_path(key):
        score += _software_alias_score(business_scope)
    exhibition_target = _exhibition_target_for_key(key)
    if exhibition_target:
        score += _exhibition_alias_score(exhibition_target, business_scope)
    engineering_target = _engineering_target_for_key(key)
    if engineering_target:
        score += _engineering_alias_score(engineering_target, key, business_scope)
    material_target = _material_target_for_key(key)
    if material_target:
        score += _material_alias_score(material_target, business_scope)
    for aliases, targets in EVIDENCE_ALIASES.items():
        if not any(alias in business_scope for alias in aliases):
            continue
        if targets:
            if key in targets:
                score += 80
        elif _key_matches_agriculture_path(key) and not _has_fertilizer_primary_business(business_scope):
            score += 40
    return score


def _alias_evidence_for_key(key: tuple[str, str, str], business_scope: str) -> list[str]:
    hits = []
    if _key_matches_fertilizer_path(key):
        hits.extend(word for word in sorted(FERTILIZER_STRONG_WORDS | FERTILIZER_WEAK_WORDS) if word in business_scope)
    equipment_target = _equipment_target_for_key(key)
    if equipment_target and _equipment_alias_score(equipment_target, business_scope) > 0:
        hits.extend(word for word in _equipment_evidence_words(equipment_target, business_scope) if word in business_scope)
    if _key_matches_consulting_path(key) and _consulting_alias_score(business_scope) > 0:
        hits.extend(word for word in sorted(CONSULTING_CONTEXT_WORDS, key=lambda item: (-len(item), item)) if word in business_scope)
    if _key_matches_software_path(key) and _software_alias_score(business_scope) > 0:
        hits.extend(word for word in sorted(SOFTWARE_CONTEXT_WORDS, key=lambda item: (-len(item), item)) if word in business_scope)
    exhibition_target = _exhibition_target_for_key(key)
    if exhibition_target and _exhibition_alias_score(exhibition_target, business_scope) > 0:
        hits.extend(word for word in sorted(EXHIBITION_CONTEXT_WORDS, key=lambda item: (-len(item), item)) if word in business_scope)
    engineering_target = _engineering_target_for_key(key)
    if engineering_target and _engineering_alias_score(engineering_target, key, business_scope) > 0:
        hits.extend(word for word in sorted(ENGINEERING_CONTEXT_WORDS, key=lambda item: (-len(item), item)) if word in business_scope)
    material_target = _material_target_for_key(key)
    if material_target and _material_alias_score(material_target, business_scope) > 0:
        hits.extend(word for word in sorted(MATERIAL_CONTEXT_WORDS, key=lambda item: (-len(item), item)) if word in business_scope)
    for aliases, targets in EVIDENCE_ALIASES.items():
        if targets and key not in targets:
            continue
        if not targets and not _key_matches_agriculture_path(key):
            continue
        hits.extend(alias for alias in aliases if alias in business_scope)
    return [f"经营范围关键词：{'、'.join(hits[:6])}"] if hits else []


def _key_matches_fertilizer_path(key: tuple[str, str, str]) -> bool:
    level_text = "".join(key)
    return "化肥" in level_text


def _fertilizer_alias_score(business_scope: str) -> int:
    if _has_fertilizer_primary_business(business_scope):
        return 180
    if any(word in business_scope for word in FERTILIZER_STRONG_WORDS):
        return 120
    if not any(word in business_scope for word in FERTILIZER_WEAK_WORDS):
        return 0
    if any(word in business_scope for word in EQUIPMENT_CONTEXT_WORDS):
        return 12
    if any(word in business_scope for word in ["研发", "生产", "销售", "制造", "经营", "农资"]):
        return 42
    return 20


def _key_matches_agriculture_path(key: tuple[str, str, str]) -> bool:
    return any(part in {"农业", "种植业", "粮食作物", "经济作物", "蔬菜作物", "水果作物"} for part in key)


def _equipment_target_for_key(key: tuple[str, str, str]) -> str:
    level_text = "".join(key)
    for _domain_words, target in EQUIPMENT_DOMAIN_TARGETS:
        if target in level_text:
            return target
    return ""


def _equipment_alias_score(target: str, business_scope: str) -> int:
    if not _has_equipment_primary_business_for_target(target, business_scope):
        return 0
    return 180


def _key_matches_consulting_path(key: tuple[str, str, str]) -> bool:
    return "技术咨询" in "".join(key)


def _consulting_alias_score(business_scope: str) -> int:
    if not _has_consulting_primary_business(business_scope):
        return 0
    if _has_direct_planting_business(business_scope) or _has_direct_livestock_or_fishery_business(business_scope):
        return 20
    return 150


def _key_matches_software_path(key: tuple[str, str, str]) -> bool:
    return key[0] == "信软技术服务" and key[1] in {"软件和信息技术", "互联网和相关服务"}


def _software_alias_score(business_scope: str) -> int:
    if not _has_software_primary_business(business_scope):
        return 0
    if "软件开发" in business_scope or "管理系统" in business_scope or "数据平台" in business_scope:
        return 150
    return 50


def _exhibition_target_for_key(key: tuple[str, str, str]) -> str:
    if key[0] != "会展服务":
        return ""
    return key[1]


def _exhibition_alias_score(target: str, business_scope: str) -> int:
    if not _has_exhibition_primary_business(business_scope):
        return 0
    domain_words = _domain_words_for_target(EXHIBITION_DOMAIN_TARGETS, target)
    if domain_words and any(word in business_scope for word in domain_words):
        return 170
    return 60


def _engineering_target_for_key(key: tuple[str, str, str]) -> str:
    level_text = "".join(key)
    if key[0] in {"机械设备厂", "建材厂", "会展服务", "信软技术服务"}:
        return ""
    for _domain_words, target in ENGINEERING_DOMAIN_TARGETS:
        if target in level_text or (target == "输变电工程" and "输变电" in level_text):
            return target
    return ""


def _engineering_alias_score(target: str, key: tuple[str, str, str], business_scope: str) -> int:
    if not _has_engineering_primary_business(business_scope):
        return 0
    domain_words = _domain_words_for_target(ENGINEERING_DOMAIN_TARGETS, target)
    if domain_words and any(word in business_scope for word in domain_words):
        if target == "水产养殖" and key[0] != "农业工程":
            return 80
        return 150
    return 0


def _material_target_for_key(key: tuple[str, str, str]) -> str:
    level_text = "".join(key)
    for _domain_words, target in MATERIAL_DOMAIN_TARGETS:
        if target in level_text:
            return target
    return ""


def _material_alias_score(target: str, business_scope: str) -> int:
    if not _has_material_primary_business(business_scope):
        return 0
    domain_words = _domain_words_for_target(MATERIAL_DOMAIN_TARGETS, target)
    if domain_words and any(word in business_scope for word in domain_words):
        return 160
    return 0


def _entered_text_support_score(key: tuple[str, str, str], record: EmployeeRecord, business_scope: str) -> int:
    if not _matches_entered_category_path(key, record.category, record.subcategory):
        return 0
    if _key_matches_agriculture_path(key) and _has_fertilizer_primary_business(business_scope):
        return 28 if _has_direct_planting_business(business_scope) else 0
    if _key_matches_agriculture_path(key) and _has_consulting_primary_business(business_scope):
        return 28 if _has_direct_planting_business(business_scope) else 0
    if _key_matches_agriculture_path(key) and _has_non_direct_business_primary(business_scope):
        return 28 if _has_direct_planting_business(business_scope) else 0
    if _key_matches_livestock_or_fishery_path(key) and _has_equipment_primary_business_for_target("农林牧渔机械", business_scope):
        return 28 if _has_direct_livestock_or_fishery_business(business_scope) else 0
    if _key_matches_livestock_or_fishery_path(key) and _has_consulting_primary_business(business_scope):
        return 28 if _has_direct_livestock_or_fishery_business(business_scope) else 0
    if _key_matches_livestock_or_fishery_path(key) and _has_non_direct_business_primary(business_scope):
        return 28 if _has_direct_livestock_or_fishery_business(business_scope) else 0
    if _key_matches_health_service_path(key) and _has_non_direct_business_primary(business_scope):
        return 0
    support_words = [record.category, *_split_category_values(record.subcategory)]
    direct_hits = [word for word in support_words if word and word in business_scope]
    if direct_hits:
        return 36
    if _agriculture_evidence_supports_entered(record, business_scope):
        return 28
    return 0


def _agriculture_evidence_supports_entered(record: EmployeeRecord, business_scope: str) -> bool:
    if _has_fertilizer_primary_business(business_scope) and not _has_direct_planting_business(business_scope):
        return False
    if _has_consulting_primary_business(business_scope) and not _has_direct_planting_business(business_scope):
        return False
    if record.category not in {"农业", "种植业"}:
        return False
    return any(word in business_scope for word in ["农产品种植", "农业活动", "农业", "农作物", "种植"])


def _has_fertilizer_primary_business(business_scope: str) -> bool:
    has_strong_word = any(word in business_scope for word in FERTILIZER_STRONG_WORDS)
    has_weak_word = any(word in business_scope for word in FERTILIZER_WEAK_WORDS)
    if not has_strong_word and not has_weak_word:
        return False
    if not has_strong_word and any(word in business_scope for word in EQUIPMENT_CONTEXT_WORDS):
        return False
    return any(word in business_scope for word in ["研发", "生产", "销售", "产品", "厂家", "核心产品", "解决方案"])


def _has_direct_planting_business(business_scope: str) -> bool:
    direct_patterns = [
        r"(?:公司|企业|基地|主营|主要|专业|从事|致力于).{0,20}种植",
        r"种植基地",
        r"种植规模",
        r"可种植",
        r"种植面积",
        r"农产品种植",
    ]
    return any(re.search(pattern, business_scope) for pattern in direct_patterns)


def _key_matches_livestock_or_fishery_path(key: tuple[str, str, str]) -> bool:
    level_text = "".join(key)
    return any(word in level_text for word in ["畜牧", "水产", "渔业", "养殖"])


def _has_equipment_primary_business_for_target(target: str, business_scope: str) -> bool:
    if not any(word in business_scope for word in EQUIPMENT_CONTEXT_WORDS):
        return False
    domain_words = _equipment_domain_words_for_target(target)
    if not any(word in business_scope for word in domain_words):
        return False
    return any(word in business_scope for word in ["研发", "生产", "制造", "销售", "产品", "厂家", "供应", "解决方案"])


def _equipment_domain_words_for_target(target: str) -> set[str]:
    for domain_words, candidate_target in EQUIPMENT_DOMAIN_TARGETS:
        if candidate_target == target:
            return domain_words
    return set()


def _equipment_evidence_words(target: str, business_scope: str) -> list[str]:
    words = set(EQUIPMENT_CONTEXT_WORDS) | _equipment_domain_words_for_target(target) | {target}
    return sorted(words, key=lambda word: (-len(word), word))


def _has_direct_livestock_or_fishery_business(business_scope: str) -> bool:
    direct_patterns = [
        r"(?:公司|企业|基地|主营|主要|专业|从事|致力于).{0,20}(?:养殖|捕捞)",
        r"养殖基地",
        r"养殖场",
        r"养殖面积",
        r"水产养殖业务",
        r"海水养殖",
        r"淡水养殖",
    ]
    return any(re.search(pattern, business_scope) for pattern in direct_patterns)


def _has_consulting_primary_business(business_scope: str) -> bool:
    if not any(word in business_scope for word in CONSULTING_PRIMARY_WORDS):
        return False
    if _has_direct_planting_business(business_scope) or _has_direct_livestock_or_fishery_business(business_scope):
        return False
    return any(word in business_scope for word in ["提供", "从事", "主营", "主要", "专业", "致力于", "服务"])


def _has_software_primary_business(business_scope: str) -> bool:
    if not any(word in business_scope for word in SOFTWARE_CONTEXT_WORDS):
        return False
    return any(word in business_scope for word in SOFTWARE_PRIMARY_WORDS)


def _has_exhibition_primary_business(business_scope: str) -> bool:
    if not any(word in business_scope for word in EXHIBITION_CONTEXT_WORDS):
        return False
    return any(word in business_scope for word in ["举办", "承办", "组织", "服务", "展示", "参展", "展览"])


def _has_engineering_primary_business(business_scope: str) -> bool:
    if not any(word in business_scope for word in ENGINEERING_CONTEXT_WORDS):
        return False
    return any(word in business_scope for word in ["承接", "施工", "设计", "建设", "安装", "总包", "承包", "运维", "改造"])


def _has_material_primary_business(business_scope: str) -> bool:
    if not any(word in business_scope for word in MATERIAL_CONTEXT_WORDS):
        return False
    return any(word in business_scope for word in PRODUCT_PRIMARY_WORDS)


def _has_non_direct_business_primary(business_scope: str) -> bool:
    return any(
        [
            _has_software_primary_business(business_scope),
            _has_exhibition_primary_business(business_scope),
            _has_engineering_primary_business(business_scope),
            _has_material_primary_business(business_scope),
        ]
    )


def _key_matches_health_service_path(key: tuple[str, str, str]) -> bool:
    return any(word in "".join(key) for word in ["卫生和社会工作", "医院", "社会工作"])


def _domain_words_for_target(targets: list[tuple[set[str], str]], target: str) -> set[str]:
    for domain_words, candidate_target in targets:
        if candidate_target == target:
            return domain_words
    return set()


def _entered_exact_candidate_keys(
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    record: EmployeeRecord,
    business_scope: str = "",
) -> list[tuple[str, str, str]]:
    subcategories = _split_category_values(record.subcategory)
    is_multi_value = len(subcategories) > 1
    keys = [key for key in grouped if _matches_entered_category_path(key, record.category, record.subcategory)]
    if not is_multi_value:
        return keys
    return [key for key in keys if _entered_text_support_score(key, record, business_scope) > 0]


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
    if not record.category:
        return False
    categories = _normalize_category_values(_split_category_values(record.category))
    return any(cat in {key[0], key[1]} for cat in categories)


def _extend_unique_keys(target: list[tuple[str, str, str]], keys: list[tuple[str, str, str]], limit: int | None = None) -> None:
    seen = set(target)
    for key in keys:
        if limit is not None and len(target) >= limit:
            break
        if key not in seen:
            target.append(key)
            seen.add(key)


def _apply_agent_result(
    result: AuditResult,
    agent_result,
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    fallback_key: tuple[str, str, str] | None = None,
    fallback_score: int = 0,
) -> AuditResult:
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
            result.status = "错误"
            result.error_type = "内部分类不存在"
            result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion, matched_text))
            result.reason += "；模型返回的一级/二级组合未在内部分类表中精确存在，不能判为正确"
            result.needs_review = True
            return result
        if _agent_correct_conflicts_with_fertilizer_primary_business(result, fallback_key, fallback_score):
            result.status = "错误"
            result.error_type = "语义分类不匹配"
            result.suggestion = _fallback_suggestion_if_changed(result, fallback_key)
            result.reason += "；外部证据显示企业主营肥料/化肥研发生产销售，作物名称更像产品适用对象，未见直接种植业务，不能判为种植业正确"
            result.needs_review = False
            return _finalize_agent_result(result)
        result.status = "正确"
        result.error_type = ""
        result.suggestion = ""
        return _finalize_agent_result(result)

    if agent_result.audit_result == "错误":
        result.status = "错误"
        result.error_type = "语义分类不匹配"
        result.suggestion = _valid_suggestion_if_changed(result, grouped, _level1_level2_suggestion(agent_result.suggestion, matched_text))
        if matched_text and not matched_key_exists:
            result.status = "疑似错误"
            result.error_type = "语义分类需复核"
            result.reason += "；模型返回的建议分类未在内部分类表中精确命中，需要人工复核"
            result.needs_review = True
        if (
            not result.suggestion
            and fallback_key
            and fallback_score >= 35
            and _can_apply_fallback_suggestion(result, agent_result)
        ):
            result.suggestion = _fallback_suggestion_if_changed(result, fallback_key)
            if result.suggestion:
                result.reason += "；模型建议无效，已根据外部证据召回结果补充建议修正"
        if not result.suggestion:
            result.reason += "；agent 未给出有效建议修正，请人工复核"
            result.needs_review = True
        return _finalize_agent_result(result)

    if agent_result.audit_result == "无法判断":
        result.status = "无法判断"
        result.error_type = "语义无法判断"
        result.suggestion = _suggestion_if_changed(result, _level1_level2_suggestion(agent_result.suggestion))
        if not result.suggestion:
            _apply_fallback_suggestion(result, fallback_key, fallback_score, agent_result)
        result.needs_review = True
        return _finalize_agent_result(result)

    result.status = "疑似错误"
    result.error_type = "语义证据不足"
    result.suggestion = _valid_suggestion_if_changed(result, grouped, _level1_level2_suggestion(agent_result.suggestion))
    if not result.suggestion:
        _apply_fallback_suggestion(result, fallback_key, fallback_score, agent_result)
    result.needs_review = True
    return _finalize_agent_result(result)


def _finalize_agent_result(result: AuditResult) -> AuditResult:
    _rewrite_generic_foreign_language_reason(result)
    return result


def _suggestion_if_changed(result: AuditResult, suggestion: str) -> str:
    """只有建议分类不同于员工原录入时才展示。"""
    value = (suggestion or "").strip()
    if not value:
        return ""
    if _normalize_category_path(value) == _normalize_category_path(f"{result.original_category} / {result.original_subcategory}"):
        return ""
    return value


def _agent_correct_conflicts_with_fertilizer_primary_business(
    result: AuditResult,
    fallback_key: tuple[str, str, str] | None,
    fallback_score: int,
) -> bool:
    if not fallback_key or fallback_score < 35:
        return False
    if not _key_matches_fertilizer_path(fallback_key):
        return False
    if result.original_category not in {"农业", "种植业"}:
        return False
    return _has_fertilizer_primary_business(result.business_scope) and not _has_direct_planting_business(result.business_scope)


def _apply_fallback_suggestion(
    result: AuditResult,
    fallback_key: tuple[str, str, str] | None,
    fallback_score: int,
    agent_result=None,
) -> None:
    if not fallback_key or fallback_score < 35:
        return
    if not _can_apply_fallback_suggestion(result, agent_result):
        return
    suggestion = _fallback_suggestion_if_changed(result, fallback_key)
    if not suggestion:
        return
    result.suggestion = suggestion
    result.reason += "；已根据外部证据召回结果补充建议修正"


def _can_apply_fallback_suggestion(result: AuditResult, agent_result=None) -> bool:
    text_parts = [
        result.reason,
        result.business_scope,
        getattr(agent_result, "reason", "") if agent_result else "",
    ]
    text = " ".join(part for part in text_parts if part)
    if not text:
        return False
    return not any(re.search(pattern, text, re.IGNORECASE) for pattern in UNUSABLE_EXTERNAL_EVIDENCE_PATTERNS)


def _fallback_suggestion_if_changed(result: AuditResult, fallback_key: tuple[str, str, str]) -> str:
    fallback_level1_level2 = _normalize_category_path(f"{fallback_key[0]} / {fallback_key[1]}")
    original_level1_level2 = _normalize_category_path(f"{result.original_category} / {result.original_subcategory}")
    if fallback_level1_level2 == original_level1_level2:
        return ""
    return _suggestion_if_changed(result, f"{fallback_key[0]} / {fallback_key[1]} / {fallback_key[2]}")


def _valid_suggestion_if_changed(
    result: AuditResult,
    grouped: dict[tuple[str, str, str], list[CategoryRule]],
    suggestion: str,
) -> str:
    value = _suggestion_if_changed(result, suggestion)
    if not value:
        return ""
    parts = _split_suggestion_parts(value)
    if len(parts) < 2:
        return ""
    level1, level2 = parts[0], parts[1]
    if any(key[0] == level1 and key[1] == level2 for key in grouped):
        return value
    return ""


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
