import threading
import time

from app.agent.classification_agent import AgentClassificationResult
from app.audit.nodes import pipeline_audit_node
from app.core.models import CategoryRule, CompanyInfo, EmployeeRecord


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


def test_pipeline_audit_node_runs_llm_agent_with_thread_pool(monkeypatch):
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

    class Provider:
        def get_company_info_for_record(self, record):
            return infos[record.company_raw.replace(" ", "")]

    state = {
        "records": records,
        "rules": [CategoryRule("A", "B", "C", "Type", ["keyword"])],
        "provider": Provider(),
        "steps": [],
    }

    result = pipeline_audit_node(state)

    assert [item.row_number for item in result["results"]] == list(range(6))
    assert len(set(agent.thread_ids)) > 1
