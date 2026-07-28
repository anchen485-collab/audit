from pathlib import Path

from openpyxl import Workbook

from app.documents.excel.category_reader import read_category_rules


def build_category_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    ws.append(["农业", "种植业", "水果作物", "类型", "苹果、梨、桃子"])
    ws.append([None, None, None, "环节", "繁育、加工、销售"])
    ws.append([None, None, "粮食作物", "类型", "玉米，水稻,小麦"])
    wb.save(path)


def test_read_category_rules_inherits_blank_category_cells_and_splits_keywords(tmp_path):
    file_path = tmp_path / "category.xlsx"
    build_category_file(file_path)

    rules = read_category_rules(file_path)

    assert len(rules) == 3
    assert rules[1].level1 == "农业"
    assert rules[1].level2 == "种植业"
    assert rules[1].level3 == "水果作物"
    assert rules[1].module_name == "环节"
    assert rules[1].keywords == ["繁育", "加工", "销售"]
    assert rules[2].level3 == "粮食作物"
    assert rules[2].keywords == ["玉米", "水稻", "小麦"]
