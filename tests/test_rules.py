from app.audit.rules import audit_record, clean_company_name
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


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
