from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.audit.graph import run_audit_workflow
from app.company.mock_provider import MockCompanyInfoProvider


def build_employee_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["日期", "姓名", "一级分类", "细分", "企业名称&官网", "环节"])
    ws.append(["7月20日", "张硕", "种植业", "水果作物", "金川县雪梨果业开发有限责任公司", "梨（销售）"])
    wb.save(path)


def build_category_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    ws.append(["农业", "种植业", "水果作物", "类型", "梨、苹果、水果"])
    ws.append([None, None, None, "环节", "繁育、加工、销售"])
    wb.save(path)


def test_run_audit_workflow_exports_result_excel(tmp_path):
    employee_file = tmp_path / "employee.xlsx"
    category_file = tmp_path / "category.xlsx"
    output_dir = tmp_path / "outputs"
    build_employee_file(employee_file)
    build_category_file(category_file)

    provider = MockCompanyInfoProvider(
        {
            "金川县雪梨果业开发有限责任公司": {
                "business_scope": "梨、水果种植、加工、销售。",
                "status": "存续",
            }
        }
    )

    state = run_audit_workflow(employee_file, category_file, output_dir, provider)

    assert state["output_path"]
    assert Path(state["output_path"]).exists()
    wb = load_workbook(state["output_path"], data_only=True)
    assert "审计明细" in wb.sheetnames
    assert "人员汇总" in wb.sheetnames
