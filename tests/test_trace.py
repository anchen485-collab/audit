import logging

import pytest

from app.core.trace import record_trace_stage, timed_stage


def test_record_trace_stage_appends_duration_and_logs(caplog):
    state = {"trace_id": "trace_test", "trace": []}

    with caplog.at_level(logging.INFO):
        record_trace_stage(state, "read_employee", 12.3456, status="success", record_count=2)

    assert state["trace"] == [
        {
            "stage": "read_employee",
            "duration_ms": 12.35,
            "status": "success",
            "record_count": 2,
        }
    ]
    assert any("audit_trace_stage_done" in record.getMessage() for record in caplog.records)
    assert any("trace_id=trace_test" in record.getMessage() for record in caplog.records)
    assert any("duration_ms=12.35" in record.getMessage() for record in caplog.records)


def test_timed_stage_records_failure_before_reraising(caplog):
    state = {"trace_id": "trace_test", "trace": []}

    with pytest.raises(ValueError), caplog.at_level(logging.INFO):
        with timed_stage(state, "query_company"):
            raise ValueError("boom")

    assert state["trace"][0]["stage"] == "query_company"
    assert state["trace"][0]["status"] == "failed"
    assert state["trace"][0]["duration_ms"] >= 0
    assert any("audit_trace_stage_failed" in record.getMessage() for record in caplog.records)
