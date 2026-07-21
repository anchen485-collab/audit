from app.audit.rules import audit_record, clean_company_name
from app.agent.classification_agent import AgentClassificationResult
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


class FakeClassificationAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def classify(self, record, company, rules):
        self.calls.append((record, company, rules))
        return self.result


def test_clean_company_name_removes_url_and_extra_spaces():
    assert clean_company_name(" 金川县雪梨果业开发有限责任公司 https://example.com ") == "金川县雪梨果业开发有限责任公司"


def test_audit_record_marks_missing_required_field_as_incomplete():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="张硕",
        category="种植业",
        subcategory="",
        company_raw="金川县雪梨果业开发有限责任公司",
        stage="梨（销售）",
    )

    result = audit_record(record, [], None)

    assert result.status == "信息缺失"
    assert result.needs_review is True
    assert "细分" in result.reason


def test_audit_record_marks_matching_scope_as_correct():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="张硕",
        category="种植业",
        subcategory="水果作物",
        company_raw="金川县雪梨果业开发有限责任公司",
        stage="梨（繁育、加工、销售）",
    )
    company = CompanyInfo(
        query_name="金川县雪梨果业开发有限责任公司",
        company_name="金川县雪梨果业开发有限责任公司",
        business_scope="水果、梨、苹果种植、加工、销售；农业技术服务。",
        status="存续",
        source="mock",
        success=True,
    )
    rules = [
        CategoryRule("农业", "种植业", "水果作物", "类型", ["苹果", "梨", "水果"]),
        CategoryRule("农业", "种植业", "水果作物", "环节", ["繁育", "加工", "销售"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.confidence >= 80
    assert result.needs_review is False


def test_audit_record_ignores_stage_when_scoring_category():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="张冰冰",
        category="种植业",
        subcategory="水果作物",
        company_raw="金川县雪梨果业开发有限责任公司",
        stage="完全不匹配的环节",
    )
    company = CompanyInfo(
        query_name="金川县雪梨果业开发有限责任公司",
        company_name="金川县雪梨果业开发有限责任公司",
        business_scope="梨、苹果、水果种植、农业技术服务。",
        status="存续",
        source="mock",
        success=True,
    )
    rules = [
        CategoryRule("农业", "种植业", "水果作物", "类型", ["苹果", "梨", "水果"]),
        CategoryRule("农业", "种植业", "水果作物", "环节", ["繁育", "加工", "销售"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.confidence >= 80
    assert "环节" not in result.reason


def test_audit_record_suggests_better_category_when_scope_mismatches():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="种植业",
        subcategory="水果作物",
        company_raw="黑龙江省佳莲种业有限公司",
        stage="苹果（销售）",
    )
    company = CompanyInfo(
        query_name="黑龙江省佳莲种业有限公司",
        company_name="黑龙江省佳莲种业有限公司",
        business_scope="水稻、玉米、大豆种子繁育、加工、销售。",
        status="存续",
        source="mock",
        success=True,
    )
    rules = [
        CategoryRule("农业", "种植业", "水果作物", "类型", ["苹果", "梨", "水果"]),
        CategoryRule("农业", "种植业", "粮食作物", "类型", ["水稻", "玉米", "大豆"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "错误"
    assert "粮食作物" in result.suggestion
    assert result.needs_review is False


def test_audit_record_can_use_classification_agent_result():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="种植业",
        subcategory="水果作物",
        company_raw="城市大米进出口有限公司",
        stage="销售",
    )
    company = CompanyInfo(
        query_name="城市大米进出口有限公司",
        company_name="城市大米进出口有限公司",
        business_scope="公司简介显示企业长期加工稻米，并出口大米到国际市场。",
        status="",
        source="website",
        success=True,
        raw={"website_url": "https://example.com"},
    )
    rules = [
        CategoryRule("农业", "种植业", "水果作物", "类型", ["水果"]),
        CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻", "大米"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="农业",
            matched_level2="种植业",
            audit_result="错误",
            confidence=92,
            reason="外部证据显示主营稻米加工和出口。",
            suggestion="农业 / 种植业",
            needs_review=False,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "错误"
    assert result.error_type == "语义分类不匹配"
    assert result.confidence == 92
    assert result.suggestion == "农业 / 种植业"
    assert result.needs_review is False
