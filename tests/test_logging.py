from pathlib import Path

from openpyxl import Workbook

from app.audit.graph import run_audit_workflow
from app.company.mock_provider import MockCompanyInfoProvider
from app.company.website_crawler import WebsiteCrawler


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"


def _build_employee_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["日期", "姓名", "一级分类", "细分", "企业名称&官网", "环节"])
    ws.append(["7月20日", "张冰冰", "种植业", "水果作物", "金川县雪梨果业开发有限责任公司", "梨（销售）"])
    wb.save(path)


def _build_category_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    ws.append(["农业", "种植业", "水果作物", "类型", "梨、苹果、水果"])
    ws.append([None, None, None, "环节", "繁育、加工、销售"])
    wb.save(path)


def test_audit_workflow_writes_important_logs(tmp_path, caplog):
    employee_file = tmp_path / "employee.xlsx"
    category_file = tmp_path / "category.xlsx"
    _build_employee_file(employee_file)
    _build_category_file(category_file)
    provider = MockCompanyInfoProvider(
        {
            "金川县雪梨果业开发有限责任公司": {
                "business_scope": "梨、水果种植、加工、销售。",
                "status": "存续",
            }
        }
    )

    with caplog.at_level("INFO"):
        run_audit_workflow(employee_file, category_file, tmp_path / "outputs", provider, job_id="test_job")

    messages = [record.getMessage() for record in caplog.records]
    assert any("audit_workflow_start" in message for message in messages)
    assert any("audit_read_employee_done" in message for message in messages)
    assert any("audit_query_company_done" in message for message in messages)
    assert any("audit_export_done" in message for message in messages)
    assert any("audit_workflow_done" in message for message in messages)


def test_website_crawler_writes_page_logs(caplog):
    pages = {
        "https://demo.com": '<html><body><a href="/about">关于我们</a></body></html>',
        "https://demo.com/about": "<html><body><p>公司简介 蔬菜种植、加工、销售。</p></body></html>",
    }

    def fake_get(url, timeout, headers):
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=4, max_depth=1, min_text_length=5)

    with caplog.at_level("INFO"):
        crawler.crawl("https://demo.com")

    messages = [record.getMessage() for record in caplog.records]
    assert any("website_crawl_start" in message for message in messages)
    assert any("website_crawl_page_success" in message for message in messages)
    assert any("website_crawl_success" in message for message in messages)
