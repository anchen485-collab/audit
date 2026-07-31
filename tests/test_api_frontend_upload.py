from fastapi.testclient import TestClient

from app.api.main import app
from tests.test_api_upload import build_category_file, build_employee_file


def test_frontend_detail_table_removes_level2_column():
    """审计明细里只展示一级分类和细分，不再单独展示二级分类。"""
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "审计明细" in response.text
    assert "二级分类" not in response.text
    assert 'colspan="11"' in response.text
    assert "/static/app.js?v=detail-table-20260731" in response.text
    assert "/static/styles.css?v=detail-table-20260731" in response.text


def test_frontend_api_upload_returns_json_payload(tmp_path, monkeypatch):
    """验证单页前端使用的 JSON 上传接口可以返回审计结果和下载链接。"""
    monkeypatch.setenv("AUDIT_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("CATEGORY_RULES_JSON_PATH", str(tmp_path / "category_rules.json"))
    monkeypatch.setenv("COMPANY_PROVIDER", "mock")
    monkeypatch.setenv("AUDIT_LLM_AGENT_ENABLED", "false")

    employee_file = tmp_path / "employee.xlsx"
    category_file = tmp_path / "category.xlsx"
    build_employee_file(employee_file)
    build_category_file(category_file)
    monkeypatch.setenv("CATEGORY_RULES_EXCEL_PATH", str(category_file))

    client = TestClient(app)
    with employee_file.open("rb") as employee_fp:
        response = client.post(
            "/api/audit/upload",
            files={
                "file": ("employee.xlsx", employee_fp, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    data = response.json()
    assert response.status_code == 200
    assert data["case_count"] == 1
    assert data["decision_count"] == 1
    assert data["metrics"]["total_count"] == 1
    assert data["download_url"].startswith("/audit/download/")
    assert data["cases"][0]["case_id"] == data["decisions"][0]["case_id"]
