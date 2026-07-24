from app.audit.scoring import score_rule_group
from app.core.models import CategoryRule


def test_score_rule_group_ignores_stage_keywords():
    rules = [
        CategoryRule("种植业", "水果作物", "热带水果类", "环节", ["销售", "加工"]),
    ]

    score, evidence = score_rule_group(
        rules,
        category="",
        subcategory="",
        business_scope="",
        stage="销售、加工",
    )

    assert score == 0
    assert evidence == []


def test_score_rule_group_still_uses_external_evidence_keywords():
    rules = [
        CategoryRule("种植业", "水果作物", "热带水果类", "类型", ["芒果", "水果"]),
    ]

    score, evidence = score_rule_group(
        rules,
        category="种植业",
        subcategory="水果作物",
        business_scope="公司主营芒果等水果种植和销售。",
        stage="",
    )

    assert score >= 40
    assert any("经营范围关键词" in item for item in evidence)
