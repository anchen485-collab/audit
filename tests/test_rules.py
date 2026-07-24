from app.audit.rules import _level1_level2_suggestion, audit_record, clean_company_name
from app.agent.classification_agent import AgentClassificationResult
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


class FakeClassificationAgent:
    def __init__(self, result, candidate_topk=None, entered_level1_expand_topk=None, evidence_topk=None):
        self.results = result if isinstance(result, list) else [result]
        self.candidate_topk = candidate_topk
        self.entered_level1_expand_topk = entered_level1_expand_topk
        self.evidence_topk = evidence_topk
        self.calls = []

    def classify(self, record, company, rules):
        result_index = min(len(self.calls), len(self.results) - 1)
        self.calls.append((record, company, rules))
        return self.results[result_index]


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


def test_audit_record_sends_topk_candidate_rules_to_classification_agent():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="Original",
        subcategory="OriginalSub",
        company_raw="Demo Company",
    )
    company = CompanyInfo(
        query_name="Demo Company",
        company_name="Demo Company",
        business_scope="freight shipping and export services",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("Agriculture", "Fruit", "Apple", "Type", ["apple"]),
        CategoryRule("Agriculture", "Grain", "Rice", "Type", ["rice"]),
        CategoryRule("Services", "Logistics", "Freight", "Type", ["freight"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_rules = agent.calls[0][2]
    assert len(passed_rules) == 1
    assert passed_rules[0].level2 == "Logistics"


def test_audit_record_keeps_entered_category_rules_in_agent_candidates():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=2)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="Exhibition",
        subcategory="Commercial Consumer",
        company_raw="Demo Company",
    )
    company = CompanyInfo(
        query_name="Demo Company",
        company_name="Demo Company",
        business_scope="cattle pasture dairy herd breeding",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("Animal Husbandry", "Livestock", "Cattle", "Type", ["cattle", "pasture", "dairy", "herd"]),
        CategoryRule("Exhibition", "Commercial Consumer", "Consumer Expo", "Type", ["expo"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_rules = agent.calls[0][2]
    assert {rule.level1 for rule in passed_rules} == {"Animal Husbandry", "Exhibition"}


def test_audit_record_prioritizes_external_evidence_when_candidate_limit_is_small():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="Exhibition",
        subcategory="Commercial Consumer",
        company_raw="Demo Company",
    )
    company = CompanyInfo(
        query_name="Demo Company",
        company_name="Demo Company",
        business_scope="cattle pasture dairy herd breeding",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("Animal Husbandry", "Livestock", "Cattle", "Type", ["cattle", "pasture", "dairy", "herd"]),
        CategoryRule("Exhibition", "Commercial Consumer", "Consumer Expo", "Type", ["expo"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_rules = agent.calls[0][2]
    assert len(passed_rules) == 1
    assert passed_rules[0].level1 == "Animal Husbandry"


def test_audit_record_expands_candidates_under_entered_level1():
    agent = FakeClassificationAgent(
        AgentClassificationResult(),
        candidate_topk=3,
        entered_level1_expand_topk=3,
        evidence_topk=0,
    )
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="Exhibition",
        subcategory="Commercial Consumer",
        company_raw="Demo Company",
    )
    company = CompanyInfo(
        query_name="Demo Company",
        company_name="Demo Company",
        business_scope="building materials and home decoration expo",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("Exhibition", "Commercial Consumer", "Consumer Expo", "Type", ["consumer"]),
        CategoryRule("Exhibition", "Building Home", "Home Expo", "Type", ["building", "home", "decoration"]),
        CategoryRule("Exhibition", "Medical Health", "Medical Expo", "Type", ["medical"]),
        CategoryRule("Animal Husbandry", "Livestock", "Cattle", "Type", ["cattle"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_level2 = {rule.level2 for rule in agent.calls[0][2]}
    assert "Commercial Consumer" in passed_level2
    assert "Building Home" in passed_level2
    assert "Livestock" not in passed_level2


def test_audit_record_retrieves_fertilizer_category_from_external_evidence_aliases():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=5, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="种植业",
        subcategory="粮食作物,经济作物,蔬菜作物,水果作物",
        company_raw="天津特沃多生物科技有限公司",
    )
    company = CompanyInfo(
        query_name="天津特沃多生物科技有限公司",
        company_name="天津特沃多生物科技有限公司",
        business_scope="公司专注于钛肥等特种肥料研发生产和销售。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["水稻", "小麦"]),
        CategoryRule("石油化工", "化学与化工工程", "化肥", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert ("石油化工", "化学与化工工程", "化肥") in passed_keys
    assert ("种植业", "粮食作物", "谷类") not in passed_keys


def test_audit_record_orders_fertilizer_candidate_before_original_table_order_fillers():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=6, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="种植业",
        subcategory="粮食作物,经济作物,蔬菜作物,水果作物",
        company_raw="河南泰格茂生物科技有限公司",
    )
    company = CompanyInfo(
        query_name="河南泰格茂生物科技有限公司",
        company_name="河南泰格茂生物科技有限公司",
        business_scope=(
            "公司专注于钛肥、水溶肥等肥料的研发、生产和销售，提供农业技术服务。"
            "泰格茂叶面肥因作物制宜，粮食作物包括小麦、水稻等，水溶肥和复合肥用于高效施肥。"
        ),
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("电力", "发电工程", "水电", "类型", ["农业技术服务"]),
        CategoryRule("连锁经营", "农资连锁", "农资门店", "类型", ["农资"]),
        CategoryRule("卫生和社会工作", "医院", "综合医院", "类型", ["服务"]),
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["水稻", "小麦", "粮食作物"]),
        CategoryRule("种植业", "经济作物", "纤维类", "类型", ["棉花"]),
        CategoryRule("石油化工", "化学与化工工程", "化肥", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_rules = agent.calls[0][2]
    assert (passed_rules[0].level1, passed_rules[0].level2, passed_rules[0].level3) == (
        "石油化工",
        "化学与化工工程",
        "化肥",
    )


def test_audit_record_does_not_overmatch_fertilizer_equipment_to_fertilizer_category():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="石油化工",
        subcategory="化肥",
        company_raw="肥料包装设备有限公司",
    )
    company = CompanyInfo(
        query_name="肥料包装设备有限公司",
        company_name="肥料包装设备有限公司",
        business_scope="公司主要生产肥料包装设备、灌装装备和自动化生产线。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("石油化工", "化学与化工工程", "化肥", "生态", ["网站", "会展"]),
        CategoryRule("机械设备厂", "专用设备厂", "包装设备", "类型", ["包装设备", "灌装装备", "生产线"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("机械设备厂", "专用设备厂", "包装设备")}


def test_audit_record_routes_aquaculture_equipment_to_agri_machinery():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="畜牧业",
        subcategory="水产",
        company_raw="水产养殖设备有限公司",
    )
    company = CompanyInfo(
        query_name="水产养殖设备有限公司",
        company_name="水产养殖设备有限公司",
        business_scope="公司主要生产水产养殖设备、增氧装备、投喂系统和循环水养殖解决方案。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("畜牧业", "水产", "淡水养殖", "全产业链", ["经营", "咨询"]),
        CategoryRule("渔业", "水产养殖", "淡水养殖", "生态", ["网站", "会展"]),
        CategoryRule("机械设备厂", "专用设备厂", "农林牧渔机械", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("机械设备厂", "专用设备厂", "农林牧渔机械")}


def test_audit_record_keeps_real_aquaculture_when_direct_farming_evidence_exists():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="畜牧业",
        subcategory="水产",
        company_raw="淡水养殖有限公司",
    )
    company = CompanyInfo(
        query_name="淡水养殖有限公司",
        company_name="淡水养殖有限公司",
        business_scope="公司主营淡水养殖业务，建设水产养殖基地，并配套使用增氧设备。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("畜牧业", "水产", "淡水养殖", "全产业链", ["经营", "咨询"]),
        CategoryRule("机械设备厂", "专用设备厂", "农林牧渔机械", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("畜牧业", "水产", "淡水养殖")}


def test_audit_record_routes_medical_equipment_to_equipment_category():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="卫生和社会工作",
        subcategory="医院",
        company_raw="医疗设备有限公司",
    )
    company = CompanyInfo(
        query_name="医疗设备有限公司",
        company_name="医疗设备有限公司",
        business_scope="公司主要研发生产医疗诊断设备、康复装备和医用检测系统。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("卫生和社会工作", "医院", "综合医院", "类型", ["诊断", "康复"]),
        CategoryRule("机械设备厂", "专用设备厂", "医疗设备", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("机械设备厂", "专用设备厂", "医疗设备")}


def test_audit_record_routes_chemical_equipment_to_equipment_category():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="石油化工",
        subcategory="化学制品",
        company_raw="化工设备有限公司",
    )
    company = CompanyInfo(
        query_name="化工设备有限公司",
        company_name="化工设备有限公司",
        business_scope="公司专业制造化工设备、反应装置和石化生产线，为化工企业提供装备解决方案。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("石油化工", "化学与化工工程", "化学制品", "类型", ["化工", "石化"]),
        CategoryRule("机械设备厂", "专用设备厂", "化工设备", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("机械设备厂", "专用设备厂", "化工设备")}


def test_audit_record_routes_agriculture_consulting_to_technical_consulting():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="种植业",
        subcategory="粮食作物",
        company_raw="农业咨询服务有限公司",
    )
    company = CompanyInfo(
        query_name="农业咨询服务有限公司",
        company_name="农业咨询服务有限公司",
        business_scope="公司主要提供农业技术咨询、种植方案设计、农技培训和作物管理解决方案。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["粮食作物", "作物", "种植"]),
        CategoryRule("信软技术服务", "软件和信息技术", "技术咨询", "类型", ["技术咨询", "方案设计", "培训"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("信软技术服务", "软件和信息技术", "技术咨询")}


def test_audit_record_keeps_real_planting_when_consulting_is_secondary():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="种植业",
        subcategory="粮食作物",
        company_raw="农业种植有限公司",
    )
    company = CompanyInfo(
        query_name="农业种植有限公司",
        company_name="农业种植有限公司",
        business_scope="公司主营粮食作物种植，建设种植基地，并为农户提供农业技术咨询服务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["粮食作物", "种植基地", "种植"]),
        CategoryRule("信软技术服务", "软件和信息技术", "技术咨询", "类型", ["技术咨询", "培训"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("种植业", "粮食作物", "谷类")}


def test_audit_record_routes_agriculture_management_system_to_software():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="种植业",
        subcategory="粮食作物",
        company_raw="农业软件有限公司",
    )
    company = CompanyInfo(
        query_name="农业软件有限公司",
        company_name="农业软件有限公司",
        business_scope="公司主要从事农业管理系统、种植数据平台和农场数字化软件开发。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["种植", "农场", "粮食作物"]),
        CategoryRule("信软技术服务", "软件和信息技术", "软件开发", "类型", ["软件开发", "管理系统", "数据平台"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("信软技术服务", "软件和信息技术", "软件开发")}


def test_audit_record_routes_medical_exhibition_to_exhibition_service():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="卫生和社会工作",
        subcategory="医院",
        company_raw="医疗展览有限公司",
    )
    company = CompanyInfo(
        query_name="医疗展览有限公司",
        company_name="医疗展览有限公司",
        business_scope="公司承办医疗器械展会和健康产业博览会，提供展览展示与会务服务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("卫生和社会工作", "医院", "综合医院", "类型", ["医疗", "健康"]),
        CategoryRule("会展服务", "医疗健康", "医疗展会", "类型", ["医疗器械", "健康", "展会"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("会展服务", "医疗健康", "医疗展会")}


def test_audit_record_routes_photovoltaic_construction_to_power_engineering():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="机械设备厂",
        subcategory="电力设备",
        company_raw="光伏工程有限公司",
    )
    company = CompanyInfo(
        query_name="光伏工程有限公司",
        company_name="光伏工程有限公司",
        business_scope="公司承接光伏电站工程设计、施工、安装和运维服务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("机械设备厂", "专用设备厂", "电子电工设备", "类型", ["光伏", "设备"]),
        CategoryRule("电力", "发电工程", "光伏", "类型", ["光伏", "电站", "施工"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("电力", "发电工程", "光伏")}


def test_audit_record_routes_waterproof_material_to_building_materials():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-24",
        name="Alex",
        category="房屋建筑",
        subcategory="建筑施工",
        company_raw="防水材料有限公司",
    )
    company = CompanyInfo(
        query_name="防水材料有限公司",
        company_name="防水材料有限公司",
        business_scope="公司研发生产建筑防水材料、防水涂料并销售功能建材产品。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("房屋建筑", "工业建筑", "厂房", "类型", ["建筑", "施工"]),
        CategoryRule("建材厂", "功能建材工程", "防水材料", "类型", ["防水材料", "防水涂料", "功能建材"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("建材厂", "功能建材工程", "防水材料")}


def test_audit_record_keeps_multivalue_entered_categories_when_evidence_supports_them():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=4, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=8,
        date="2026-07-24",
        name="Alex",
        category="种植业",
        subcategory="粮食作物,经济作物",
        company_raw="吉林老爷岭农业集团有限公司",
    )
    company = CompanyInfo(
        query_name="吉林老爷岭农业集团有限公司",
        company_name="吉林老爷岭农业集团有限公司",
        business_scope="企业从事农产品种植、加工等农业活动，包含粮食作物和经济作物相关业务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("电力", "发电工程", "水电", "类型", ["水力发电"]),
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["水稻", "玉米"]),
        CategoryRule("种植业", "经济作物", "油料作物", "类型", ["油菜", "大豆"]),
        CategoryRule("卫生和社会工作", "医院", "综合医院", "类型", ["门诊"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert ("种植业", "粮食作物", "谷类") in passed_keys
    assert ("种植业", "经济作物", "油料作物") in passed_keys


def test_audit_record_retrieves_veterinary_drug_category_from_external_evidence_aliases():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="畜牧业",
        subcategory="家禽",
        company_raw="山东临沂兽药有限公司",
    )
    company = CompanyInfo(
        query_name="山东临沂兽药有限公司",
        company_name="山东临沂兽药有限公司",
        business_scope="公司主要从事兽药、动物保健品研发生产和销售。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("畜牧业", "家禽", "鸡", "全产业链", ["经营", "咨询"]),
        CategoryRule("医药工业", "制药工业", "兽用药品", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert ("医药工业", "制药工业", "兽用药品") in passed_keys
    assert ("畜牧业", "家禽", "鸡") not in passed_keys


def test_audit_record_ignores_generic_ecology_keywords_when_retrieving_candidates():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=1, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="电力",
        subcategory="发电工程",
        company_raw="智能系统有限公司",
    )
    company = CompanyInfo(
        query_name="智能系统有限公司",
        company_name="智能系统有限公司",
        business_scope="公司主要提供软件开发、管理系统和数据平台建设服务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("电力", "发电工程", "水电", "生态", ["网站", "会展", "软件"]),
        CategoryRule("信软技术服务", "软件和信息技术", "软件开发", "类型", ["软件开发", "APP"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert passed_keys == {("信软技术服务", "软件和信息技术", "软件开发")}


def test_audit_record_retrieves_forestry_category_for_forest_fire_evidence():
    agent = FakeClassificationAgent(AgentClassificationResult(), candidate_topk=2, entered_level1_expand_topk=0)
    record = EmployeeRecord(
        row_number=2,
        date="2026-07-23",
        name="Alex",
        category="信软技术服务",
        subcategory="软件和信息技术",
        company_raw="森林防火监测有限公司",
    )
    company = CompanyInfo(
        query_name="森林防火监测有限公司",
        company_name="森林防火监测有限公司",
        business_scope="企业从事森林防火、林长制、林业巡护和森林资源保护相关业务，建设森林防火监测平台。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("信软技术服务", "软件和信息技术", "软件开发", "类型", ["软件开发", "管理系统", "数据平台"]),
        CategoryRule("林业", "生态公益林", "防护林", "全产业链", ["经营", "咨询", "造林", "营林"]),
        CategoryRule("生态环境", "生态治理工程", "森林生态修复", "生态", ["网站", "会展"]),
    ]

    audit_record(record, rules, company, classification_agent=agent)

    passed_keys = {(rule.level1, rule.level2, rule.level3) for rule in agent.calls[0][2]}
    assert ("林业", "生态公益林", "防护林") in passed_keys
    assert ("生态环境", "生态治理工程", "森林生态修复") in passed_keys
    assert ("信软技术服务", "软件和信息技术", "软件开发") not in passed_keys


def test_audit_record_marks_partial_current_match_with_scope_evidence_as_reviewable_correct():
    record = EmployeeRecord(
        row_number=3,
        date="7月22日",
        name="安鹏",
        category="会展服务",
        subcategory="医疗健康",
        company_raw="湖北贸促商务服务有限公司",
    )
    company = CompanyInfo(
        query_name="湖北贸促商务服务有限公司",
        company_name="湖北贸促商务服务有限公司",
        business_scope="武汉医疗器械展览会，为医疗诊断、治疗、检验、康复等产品展示和技术交流提供平台。",
        status="",
        source="website",
        success=True,
        raw={"website_url": "http://www.hbexpo.org.cn/"},
    )
    rules = [
        CategoryRule("会展服务", "医疗健康", "医疗展会", "类型", ["医疗器械", "医疗诊断"]),
        CategoryRule("会展服务", "交通物流", "物流展会", "类型", ["物流", "货运"]),
    ]

    result = audit_record(record, rules, company)

    assert result.status == "正确"
    assert result.confidence >= 60
    assert result.error_type == "低置信度匹配"
    assert result.needs_review is True
    assert result.suggestion == ""
    assert "经营范围关键词" in result.reason


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


def test_audit_record_drops_agent_suggestion_when_same_as_entered_category():
    record = EmployeeRecord(
        row_number=11,
        date="7月22日",
        name="安鹏",
        category="会展服务",
        subcategory="文化教育娱乐",
        company_raw="测试会展企业",
    )
    company = CompanyInfo(
        query_name="测试会展企业",
        company_name="测试会展企业",
        business_scope="企业从事展览展示服务和展台搭建。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("会展服务", "文化教育娱乐", "文化展会", "类型", ["文化", "教育", "娱乐"]),
        CategoryRule("会展服务", "交通物流", "汽车展会", "类型", ["汽车", "物流"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="会展服务",
            matched_level2="文化教育娱乐",
            audit_result="疑似错误",
            confidence=60,
            reason="证据不足，无法确定是否属于文化教育娱乐。",
            suggestion="会展服务 / 文化教育娱乐",
            needs_review=True,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "疑似错误"
    assert result.suggestion == ""


def test_audit_record_drops_agent_suggestion_when_not_in_internal_rules():
    record = EmployeeRecord(
        row_number=12,
        date="7月22日",
        name="安鹏",
        category="种植业",
        subcategory="粮食作物,经济作物,蔬菜作物,水果作物",
        company_raw="天津特沃多生物科技有限公司",
    )
    company = CompanyInfo(
        query_name="天津特沃多生物科技有限公司",
        company_name="天津特沃多生物科技有限公司",
        business_scope="公司专注于钛肥等肥料研发生产和销售。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["水稻", "小麦"]),
        CategoryRule("石油化工", "化学与化工工程", "化肥", "生态", ["网站", "会展"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            matched_level1="种植业",
            matched_level2="无合适匹配",
            audit_result="错误",
            confidence=80,
            reason="肥料生产销售不属于作物种植。",
            suggestion="种植业 / 无合适匹配",
            needs_review=True,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "疑似错误"
    assert result.error_type == "语义分类需复核"
    assert result.suggestion == "石油化工 / 化学与化工工程 / 化肥"
    assert "补充建议修正" in result.reason
    assert result.needs_review is True


def test_audit_record_adds_fertilizer_fallback_when_agent_returns_retrieval_gap():
    record = EmployeeRecord(
        row_number=13,
        date="7月24日",
        name="安鹏",
        category="种植业",
        subcategory="粮食作物,经济作物,蔬菜作物,水果作物",
        company_raw="河南泰格茂生物科技有限公司",
    )
    company = CompanyInfo(
        query_name="河南泰格茂生物科技有限公司",
        company_name="河南泰格茂生物科技有限公司",
        business_scope="公司主要从事钛肥、水溶肥等肥料的研发、生产和销售，提供农业技术服务。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("种植业", "粮食作物", "谷类", "类型", ["水稻", "小麦"]),
        CategoryRule("石油化工", "化学与化工工程", "化肥", "生态", ["网站", "会展"]),
    ]
    agent = FakeClassificationAgent(
        AgentClassificationResult(
            audit_result="疑似错误",
            confidence=70,
            reason="内部分类表未包含农资、肥料相关的分类，候选召回可能不足，建议复核。",
            suggestion="",
            needs_review=True,
        )
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert result.status == "疑似错误"
    assert result.suggestion == "石油化工 / 化学与化工工程 / 化肥"
    assert "补充建议修正" in result.reason


def test_audit_record_runs_full_category_review_when_agent_reports_retrieval_gap():
    record = EmployeeRecord(
        row_number=14,
        date="7月24日",
        name="安宁",
        category="农业",
        subcategory="种植业",
        company_raw="示例农业有限公司",
    )
    company = CompanyInfo(
        query_name="示例农业有限公司",
        company_name="示例农业有限公司",
        business_scope="公司主要从事水稻、小麦等粮食作物种植。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("农业", "种植业", "粮食作物", "类型", ["水稻", "小麦"]),
        CategoryRule("石油化工", "化学与化工工程", "化肥", "类型", ["化肥"]),
        CategoryRule("信软技术服务", "软件和信息技术", "软件开发", "类型", ["软件"]),
    ]
    agent = FakeClassificationAgent(
        [
            AgentClassificationResult(
                audit_result="无法判断",
                confidence=40,
                reason="候选召回不足，内部分类表未包含明确的农业分类。",
                needs_review=True,
            ),
            AgentClassificationResult(
                matched_level1="农业",
                matched_level2="种植业",
                matched_level3="粮食作物",
                audit_result="正确",
                confidence=90,
                reason="全量分类表中存在农业 / 种植业 / 粮食作物，且证据显示公司从事粮食作物种植。",
                needs_review=False,
            ),
        ],
        candidate_topk=1,
        entered_level1_expand_topk=0,
        evidence_topk=1,
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert len(agent.calls) == 2
    assert len(agent.calls[0][2]) < len(rules)
    assert agent.calls[1][2] == rules
    assert result.status == "正确"
    assert "已触发全量分类表复核" in result.reason
    assert result.needs_review is False


def test_audit_record_runs_full_category_review_when_agent_returns_invalid_path():
    record = EmployeeRecord(
        row_number=15,
        date="7月24日",
        name="安宁",
        category="会展服务",
        subcategory="工业制造,建筑家居",
        company_raw="示例会展有限公司",
    )
    company = CompanyInfo(
        query_name="示例会展有限公司",
        company_name="示例会展有限公司",
        business_scope="企业主营业务为展台设计、展台搭建、主场运营、厅馆建造，服务覆盖工业制造和建筑家居行业。",
        status="",
        source="website",
        success=True,
    )
    rules = [
        CategoryRule("会展服务", "工业制造", "展台设计", "行业", ["工业制造", "展台设计"]),
        CategoryRule("会展服务", "建筑家居", "展台搭建", "行业", ["建筑家居", "展台搭建"]),
        CategoryRule("管理服务", "咨询服务", "企业咨询", "类型", ["咨询"]),
    ]
    agent = FakeClassificationAgent(
        [
            AgentClassificationResult(
                matched_level1="会展服务",
                matched_level2="工业制造,建筑家居,医疗健康",
                audit_result="正确",
                confidence=88,
                reason="企业属于会展服务，细分覆盖多个行业。",
                needs_review=False,
            ),
            AgentClassificationResult(
                matched_level1="会展服务",
                matched_level2="工业制造,建筑家居",
                audit_result="正确",
                confidence=92,
                reason="全量分类表中存在对应会展服务行业细分。",
                needs_review=False,
            ),
        ],
        candidate_topk=1,
        entered_level1_expand_topk=0,
        evidence_topk=1,
    )

    result = audit_record(record, rules, company, classification_agent=agent)

    assert len(agent.calls) == 2
    assert agent.calls[1][2] == rules
    assert result.status == "正确"
    assert "已触发全量分类表复核" in result.reason
    assert "未在内部分类表中精确存在" not in result.reason


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
