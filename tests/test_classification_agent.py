from app.agents.classification import ClassificationAgent, format_category_rules_for_agent, parse_agent_result
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


class CaptureChatClient:
    def __init__(self):
        self.messages = []

    def complete_json(self, messages):
        self.messages = messages
        return {
            "matched_level1": "农业",
            "matched_level2": "种植业",
            "audit_result": "正确",
            "confidence": 90,
            "reason": "外部证据支持一级和二级分类。",
            "suggestion": "",
            "needs_review": False,
        }


def test_format_category_rules_for_agent_groups_rules():
    rules = [
        CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻", "大米"]),
        CategoryRule("农业", "种植业", "谷类作物", "环节", ["加工", "销售"]),
    ]

    text = format_category_rules_for_agent(rules)

    assert "一级=农业" in text
    assert "二级=种植业" in text
    assert "三级=谷类作物" in text
    assert "类型: 水稻、大米" in text
    assert "环节" not in text
    assert "加工" not in text
    assert "销售" not in text


def test_parse_agent_result_normalizes_output():
    result = parse_agent_result(
        {
            "matched_level1": "农业",
            "matched_level2": "种植业",
            "matched_module": "环节",
            "matched_keywords": "水稻、大米",
            "audit_result": "错误",
            "confidence": "88",
            "reason": "外部证据显示主营水稻加工。",
            "suggestion": "农业 / 种植业",
            "needs_review": False,
        }
    )

    assert result.audit_result == "错误"
    assert result.confidence == 88
    assert result.matched_keywords == ["水稻", "大米"]
    assert result.needs_review is False


def test_classification_agent_prompt_allows_subcategory_to_be_level2_or_level3():
    client = CaptureChatClient()
    agent = ClassificationAgent(client)
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="农业",
        subcategory="种植业",
        company_raw="测试企业",
        stage="销售",
    )
    company = CompanyInfo(
        query_name="测试企业",
        company_name="测试企业",
        business_scope="公司简介显示主营水稻种植。",
        status="",
        source="website",
        success=True,
    )

    result = agent.classify(record, company, [CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻"])])
    user_prompt = client.messages[1]["content"]

    assert result.audit_result == "正确"
    assert "细分可能是内部二级品类，也可能是内部三级品类" in user_prompt
    assert "细分允许同时填写多个二级或三级品类" in user_prompt
    assert "不要要求只选择一个“最匹配”的二级分类" in user_prompt
    assert "如果命中多个二级品类，可用逗号分隔" in user_prompt
    assert "环节不作为判断正确或错误的标准" in user_prompt
    assert "当前环节" not in user_prompt
    assert '"matched_level1"' in user_prompt
    assert '"matched_level2"' in user_prompt
    assert '"matched_level3"' in user_prompt


def test_classification_agent_prompt_handles_foreign_language_evidence_semantically():
    client = CaptureChatClient()
    agent = ClassificationAgent(client)
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="Alex",
        category="种植业",
        subcategory="水果作物",
        company_raw="Example Farm",
    )
    company = CompanyInfo(
        query_name="Example Farm",
        company_name="Example Farm",
        business_scope="The company grows apples, pears and citrus fruit in orchard planting bases.",
        status="",
        source="website",
        success=True,
    )

    agent.classify(record, company, [CategoryRule("农业", "种植业", "水果作物", "类型", ["苹果", "梨", "水果"])])
    system_prompt = client.messages[0]["content"]
    user_prompt = client.messages[1]["content"]

    assert "英文、西语等外文" in system_prompt
    assert "先按语义理解业务含义" in user_prompt
    assert "不要因为外文证据没有直接出现中文分类关键词" in user_prompt


def test_format_category_rules_for_agent_filters_stage_module():
    rules = [
        CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻", "大米"]),
        CategoryRule("农业", "种植业", "谷类作物", "环节", ["加工", "销售"]),
    ]

    text = format_category_rules_for_agent(rules)

    assert "类型: 水稻、大米" in text
    assert "环节" not in text
    assert "加工" not in text
    assert "销售" not in text


def test_classification_agent_prompt_does_not_include_stage():
    client = CaptureChatClient()
    agent = ClassificationAgent(client)
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="农业",
        subcategory="种植业",
        company_raw="测试企业",
        stage="销售",
    )
    company = CompanyInfo(
        query_name="测试企业",
        company_name="测试企业",
        business_scope="公司简介显示主营水稻种植。",
        status="",
        source="website",
        success=True,
    )

    agent.classify(record, company, [CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻"])])
    user_prompt = client.messages[1]["content"]

    assert "当前环节" not in user_prompt
    assert "销售" not in user_prompt


def test_classification_agent_prompt_marks_full_category_review_table():
    client = CaptureChatClient()
    agent = ClassificationAgent(client)
    agent.full_category_review = True
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="种植业",
        subcategory="粮食作物",
        company_raw="测试企业",
    )
    company = CompanyInfo(
        query_name="测试企业",
        company_name="测试企业",
        business_scope="公司简介显示主营氮肥生产销售。",
        status="",
        source="website",
        success=True,
    )

    agent.classify(
        record,
        company,
        [CategoryRule("石油化工", "化学与化工工程", "化肥", "类型", ["氮肥", "化肥"])],
    )
    user_prompt = client.messages[1]["content"]

    assert "下面的内部分类表是完整分类表" in user_prompt
    assert "不要再以“候选未包含”“候选召回不足”为理由降级判断" in user_prompt


def test_classification_agent_writes_timing_log(caplog):
    client = CaptureChatClient()
    agent = ClassificationAgent(client)
    record = EmployeeRecord(
        row_number=2,
        date="7月20日",
        name="相阳",
        category="农业",
        subcategory="种植业",
        company_raw="测试企业",
    )
    company = CompanyInfo(
        query_name="测试企业",
        company_name="测试企业",
        business_scope="公司简介显示主营水稻种植。",
        status="",
        source="website",
        success=True,
    )

    with caplog.at_level("INFO"):
        agent.classify(record, company, [CategoryRule("农业", "种植业", "谷类作物", "类型", ["水稻"])])

    messages = [record.getMessage() for record in caplog.records]
    assert any("classification_agent_timing" in message for message in messages)
    assert any("duration_ms=" in message for message in messages)
    assert not any("api_key" in message.lower() for message in messages)
