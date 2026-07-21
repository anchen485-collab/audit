from collections import defaultdict

from app.core.models import CategoryRule


def contains_any(text: str, words: list[str]) -> list[str]:
    """返回在文本中出现过的关键词。"""
    return [word for word in words if word and word in text]


def group_rules(rules: list[CategoryRule]) -> dict[tuple[str, str, str], list[CategoryRule]]:
    """按一二三级品类聚合规则，便于计算分类得分。"""
    grouped: dict[tuple[str, str, str], list[CategoryRule]] = defaultdict(list)
    for rule in rules:
        grouped[(rule.level1, rule.level2, rule.level3)].append(rule)
    return dict(grouped)


def score_rule_group(
    rules: list[CategoryRule],
    category: str,
    subcategory: str,
    business_scope: str,
) -> tuple[int, list[str]]:
    """计算某个分类组合与当前记录的匹配分。"""
    if not rules:
        return 0, []

    score = 0
    evidence: list[str] = []
    first = rules[0]
    if category and category in {first.level1, first.level2, first.level3}:
        score += 20
        evidence.append(f"分类命中：{category}")
    if subcategory and subcategory in {first.level1, first.level2, first.level3}:
        score += 20
        evidence.append(f"细分命中：{subcategory}")

    all_keywords = []
    for rule in rules:
        if rule.module_name == "环节":
            continue
        all_keywords.extend(rule.keywords)

    scope_hits = contains_any(business_scope, list(dict.fromkeys(all_keywords)))
    score += min(len(scope_hits) * 14, 50)
    if scope_hits:
        evidence.append(f"经营范围关键词：{'、'.join(scope_hits[:6])}")

    return min(score, 100), evidence
