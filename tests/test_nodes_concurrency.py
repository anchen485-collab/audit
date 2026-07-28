import threading
import time

from app.agents.classification import AgentClassificationResult
from app.audit.nodes import audit_records_node, query_company_info_node
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


class SlowProvider:
    def __init__(self):
        self.thread_ids = []
        self.calls = []
        self.lock = threading.Lock()

    def get_company_info_for_record(self, record):
        with self.lock:
            self.thread_ids.append(threading.get_ident())
            self.calls.append(record.company_name or record.company_raw)
        time.sleep(0.03)
        return CompanyInfo(
            query_name=record.company_name,
            company_name=record.company_name,
            business_scope="keyword evidence",
            status="",
            source="website",
            success=True,
        )


class SlowClassificationAgent:
    candidate_topk = None
    entered_level1_expand_topk = None
    evidence_topk = None

    def __init__(self):
        self.thread_ids = []
        self.lock = threading.Lock()

    def classify(self, record, company, rules):
        with self.lock:
            self.thread_ids.append(threading.get_ident())
        time.sleep(0.03)
        return AgentClassificationResult()


class TrackingClassificationAgent:
    candidate_topk = None
    entered_level1_expand_topk = None
    evidence_topk = None

    def __init__(self):
        self.active_count = 0
        self.max_active_count = 0
        self.lock = threading.Lock()

    def classify(self, record, company, rules):
        with self.lock:
            self.active_count += 1
            self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            time.sleep(0.03)
            return AgentClassificationResult()
        finally:
            with self.lock:
                self.active_count -= 1


def test_query_company_info_node_runs_provider_with_thread_pool(monkeypatch):
    provider = SlowProvider()
    monkeypatch.setenv("WEBSITE_CRAWL_CONCURRENCY", "4")

    records = [
        EmployeeRecord(
            row_number=index,
            date="2026-07-23",
            name=f"User {index}",
            category="A",
            subcategory="B",
            company_raw=f"Company {index}",
        )
        for index in range(6)
    ]
    state = {
        "records": records,
        "provider": provider,
        "steps": [],
    }

    result = query_company_info_node(state)

    assert set(result["company_infos"]) == {f"Company{index}" for index in range(6)}
    assert len(set(provider.thread_ids)) > 1


def test_query_company_info_node_deduplicates_company_names(monkeypatch):
    provider = SlowProvider()
    monkeypatch.setenv("WEBSITE_CRAWL_CONCURRENCY", "4")
    records = [
        EmployeeRecord(2, "2026-07-23", "User 1", "A", "B", "Company A"),
        EmployeeRecord(3, "2026-07-23", "User 2", "A", "B", "Company A"),
    ]

    result = query_company_info_node({"records": records, "provider": provider, "steps": []})

    assert list(result["company_infos"]) == ["CompanyA"]
    assert provider.calls == ["CompanyA"]


def test_audit_records_node_runs_llm_agent_with_thread_pool(monkeypatch):
    agent = SlowClassificationAgent()
    monkeypatch.setattr("app.audit.nodes.build_classification_agent_from_env", lambda: agent)
    monkeypatch.setenv("AUDIT_LLM_CONCURRENCY", "4")

    records = [
        EmployeeRecord(
            row_number=index,
            date="2026-07-23",
            name=f"User {index}",
            category="A",
            subcategory="B",
            company_raw=f"Company {index}",
        )
        for index in range(6)
    ]
    infos = {
        f"Company{index}": CompanyInfo(
            query_name=f"Company {index}",
            company_name=f"Company {index}",
            business_scope="keyword evidence",
            status="",
            source="website",
            success=True,
        )
        for index in range(6)
    }

    state = {
        "records": records,
        "rules": [CategoryRule("A", "B", "C", "Type", ["keyword"])],
        "company_infos": infos,
        "steps": [],
    }

    result = audit_records_node(state)

    assert [item.row_number for item in result["results"]] == list(range(6))
    assert len(set(agent.thread_ids)) > 1


def test_audit_records_node_uses_llm_concurrency_env(monkeypatch):
    agent = TrackingClassificationAgent()
    monkeypatch.setattr("app.audit.nodes.build_classification_agent_from_env", lambda: agent)
    monkeypatch.setenv("AUDIT_LLM_CONCURRENCY", "1")

    records = [
        EmployeeRecord(
            row_number=index,
            date="2026-07-23",
            name=f"User {index}",
            category="A",
            subcategory="B",
            company_raw=f"Company {index}",
        )
        for index in range(4)
    ]

    state = {
        "records": records,
        "rules": [CategoryRule("A", "B", "C", "Type", ["keyword"])],
        "company_infos": {
            f"Company{index}": CompanyInfo(
                query_name=f"Company {index}",
                company_name=f"Company {index}",
                business_scope="keyword evidence",
                status="",
                source="website",
                success=True,
            )
            for index in range(4)
        },
        "steps": [],
    }

    audit_records_node(state)

    assert agent.max_active_count == 1


def test_query_company_info_node_handles_empty_records():
    class Provider:
        def get_company_info_for_record(self, record):
            raise AssertionError("provider should not be called for empty input")

    result = query_company_info_node({"records": [], "provider": Provider(), "steps": []})

    assert result["company_infos"] == {}
    assert result["steps"] == ["查询企业 0 家"]


def test_audit_records_node_handles_empty_records(monkeypatch):
    monkeypatch.setattr("app.audit.nodes.build_classification_agent_from_env", lambda: None)

    result = audit_records_node(
        {
            "records": [],
            "rules": [CategoryRule("A", "B", "C", "Type", ["keyword"])],
            "company_infos": {},
            "steps": [],
        }
    )

    assert result["results"] == []
    assert result["steps"] == ["完成审计 0 条"]
