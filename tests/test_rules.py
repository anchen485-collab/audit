from app.audit.rules import _level1_level2_suggestion, audit_record, clean_company_name
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


def test_audit_record_marks_contained_entered_category_as_correct_with_notice():
    record = EmployeeRecord(
        row_number=2,
        date="7月22日",
        name="安安",
        category="电力",
        subcategory="发电工程",
        company_raw="综合能源建设有限公司",
    )
    company = CompanyInfo(
        query_name="综合能源建设有限公司",
        company_name="综合能源建设有限公司",
        business_scope="公司业务领域覆盖发电工程和输变电工程，提供电力项目建设服务。",
        status="",
        source="website",
        success=True,
        raw={"website_url": "https://example.com"},
    )
    rules = [
        CategoryRule("能源服务", "电力", "发电工程", "类型", ["火力发电", "水力发电"]),
        CategoryRule("能源服务", "电力", "输变电工程", "类型", ["输变电工程", "变电站"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.error_type == "补充信息提示"
    assert result.needs_review is True
    assert result.suggestion == ""
    assert "发电工程" in result.reason
    assert "信息" in result.reason


def test_audit_record_allows_subcategory_to_be_internal_level2():
    record = EmployeeRecord(
        row_number=2,
        date="7月22日",
        name="安安",
        category="种植业",
        subcategory="蔬菜作物",
        company_raw="广东永锋农产品发展有限公司",
    )
    company = CompanyInfo(
        query_name="广东永锋农产品发展有限公司",
        company_name="广东永锋农产品发展有限公司",
        business_scope="公司专业从事蔬菜作物订单种植，包含白菜、菠菜等绿色蔬菜供应。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "蔬菜作物", "叶菜类", "全品类", ["白菜", "菠菜", "蔬菜"]),
        CategoryRule("种植业", "蔬菜作物", "根茎类", "全品类", ["土豆", "红薯"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.suggestion == ""
    assert "蔬菜作物" in result.reason


def test_audit_record_allows_subcategory_to_be_internal_level3():
    record = EmployeeRecord(
        row_number=3,
        date="7月22日",
        name="安安",
        category="种植业",
        subcategory="叶菜类",
        company_raw="广东永锋农产品发展有限公司",
    )
    company = CompanyInfo(
        query_name="广东永锋农产品发展有限公司",
        company_name="广东永锋农产品发展有限公司",
        business_scope="公司基地种植叶菜类绿色蔬菜，包含白菜、菠菜等产品。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "蔬菜作物", "叶菜类", "全品类", ["白菜", "菠菜", "蔬菜"]),
        CategoryRule("种植业", "蔬菜作物", "根茎类", "全品类", ["土豆", "红薯"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.suggestion == ""
    assert "叶菜类" in result.reason


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


def test_audit_record_calls_classification_agent_when_website_evidence_is_english():
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="信息科技",
            matched_level2="软件服务",
            audit_result="正确",
            confidence=82,
            reason="英文官网证据可支持分类。",
            needs_review=False,
        )
    )
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="张冰冰",
        category="信息科技",
        subcategory="软件服务",
        company_raw="图索科技（上海）有限公司",
        website_url="https://demo.com",
    )
    company = CompanyInfo(
        query_name="图索科技（上海）有限公司",
        company_name="图索科技（上海）有限公司",
        business_scope="From Source to Sea Protection and restoration of fish migration in river",
        status="",
        source="website",
        success=True,
        raw={"website_url": "https://demo.com"},
    )
    rules = [CategoryRule("信息科技", "软件服务", "生态监测", "类型", ["数据平台"])]

    result = audit_record(record, rules, company, classification_agent=agent)

    assert agent.calls
    assert result.status == "正确"
    assert "大模型语义判断" in result.reason


def test_audit_record_trims_agent_suggestion_to_level1_and_level2():
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
        CategoryRule("种植业", "水果作物", "热带水果类", "类型", ["水果"]),
        CategoryRule("种植业", "粮食作物", "谷物类", "类型", ["水稻", "大米"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="种植业",
            matched_level2="粮食作物",
            audit_result="错误",
            confidence=90,
            reason="外部证据显示主营稻米加工和出口。",
            suggestion="一级：种植业 / 二级：粮食作物 / 三级：谷物类",
            needs_review=False,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.suggestion == "种植业 / 粮食作物"
    assert "谷物类" not in result.suggestion


def test_level1_level2_suggestion_extracts_labeled_second_level_without_third_level():
    assert (
        _level1_level2_suggestion("建议将细分改为“鸡”（二级=家禽，三级=鸡）", "养殖业 / 家禽")
        == "养殖业 / 家禽"
    )
    assert (
        _level1_level2_suggestion("二级品类：专用设备厂 / 三级品类：农林牧渔机械", "机械设备厂 / 专用设备厂")
        == "机械设备厂 / 专用设备厂"
    )
    assert (
        _level1_level2_suggestion("粮食作物 / 农副食品加工 / 粮食加工")
        == "粮食作物 / 农副食品加工"
    )


def test_agent_cannot_mark_nonexistent_level_pair_as_correct():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="畜牧业",
        subcategory="家畜养殖",
        company_raw="测试牧业有限公司",
        stage="育种",
    )
    company = CompanyInfo(
        query_name="测试牧业有限公司",
        company_name="测试牧业有限公司",
        business_scope="企业主营家禽、家畜养殖和销售。",
        status="",
        source="website",
        success=True,
        raw={"website_url": "https://example.com"},
    )
    rules = [
        CategoryRule("畜牧业", "畜牧", "家畜", "类型", ["家畜", "牛", "羊"]),
        CategoryRule("畜牧业", "家禽", "鸡", "类型", ["鸡", "鸭"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="畜牧业",
            matched_level2="家畜养殖",
            audit_result="正确",
            confidence=95,
            reason="外部证据提到家畜养殖。",
            suggestion="",
            needs_review=False,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "错误"
    assert result.error_type == "内部分类不存在"
    assert result.needs_review is True
    assert "不能判为正确" in result.reason


def test_agent_can_mark_multiple_existing_subcategories_as_correct():
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="张硕",
        category="种植业",
        subcategory="水果作物，蔬菜作物",
        company_raw="测试农产品公司",
    )
    company = CompanyInfo(
        query_name="测试农产品公司",
        company_name="测试农产品公司",
        business_scope="外部证据显示公司主要从事水果和蔬菜的种植。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("农业", "种植业", "水果作物", "类型", ["水果"]),
        CategoryRule("农业", "种植业", "蔬菜作物", "类型", ["蔬菜"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="农业",
            matched_level2="种植业",
            audit_result="正确",
            confidence=90,
            reason="外部证据显示公司主要从事水果和蔬菜的种植。",
            suggestion="",
            needs_review=False,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "正确"
    assert result.error_type == ""
    assert result.needs_review is False


def test_agent_can_mark_existing_level3_subcategory_as_correct():
    record = EmployeeRecord(
        row_number=2,
        date="7月22日",
        name="安安",
        category="种植业",
        subcategory="叶菜类",
        company_raw="测试蔬菜企业",
    )
    company = CompanyInfo(
        query_name="测试蔬菜企业",
        company_name="测试蔬菜企业",
        business_scope="企业主营叶菜类蔬菜种植和供应。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "蔬菜作物", "叶菜类", "全品类", ["白菜", "菠菜"]),
        CategoryRule("种植业", "蔬菜作物", "根茎类", "全品类", ["土豆", "红薯"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="种植业",
            matched_level2="蔬菜作物",
            matched_level3="叶菜类",
            audit_result="正确",
            confidence=91,
            reason="外部证据提到叶菜类蔬菜。",
            suggestion="",
            needs_review=False,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "正确"
    assert result.error_type == ""
    assert result.needs_review is False
