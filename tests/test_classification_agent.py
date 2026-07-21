from app.agent.classification_agent import ClassificationAgent, format_category_rules_for_agent, parse_agent_result
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


def test_classification_agent_prompt_only_requires_level1_and_level2():
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
    assert "只判断一级品类和二级品类" in user_prompt
    assert "环节不作为判断正确或错误的标准" in user_prompt
    assert "当前环节" not in user_prompt
    assert '"matched_level1"' in user_prompt
    assert '"matched_level2"' in user_prompt
    assert '"matched_level3"' not in user_prompt


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
