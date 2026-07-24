from pathlib import Path

from openpyxl import Workbook

from app.category.rule_index import (
    build_category_rule_json,
    load_category_rule_index,
    load_category_rules_from_config,
    load_category_rules_from_json,
)


def build_category_file(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["一级品类", "二级品类", "三级品类", "模块名称", "子模块列表"])
    ws.append(["种植业", "蔬菜作物", "叶菜类", "全品类", "白菜、菠菜、蔬菜"])
    ws.append([None, None, None, "环节", "种植、加工、销售"])
    ws.append(["食品工业", "农副食品加工", "蔬菜加工", "类型", "净菜、预制菜"])
    wb.save(path)


def test_build_category_rule_json_creates_tree_and_keyword_index(tmp_path):
    excel_path = tmp_path / "category.xlsx"
    json_path = tmp_path / "category_rules.json"
    build_category_file(excel_path)

    data = build_category_rule_json(excel_path, json_path)

    assert json_path.exists()
    assert data["version"] == 1
    assert len(data["rules"]) == 3
    assert "种植业" in data["category_tree"]
    assert "蔬菜作物" in data["category_tree"]["种植业"]
    assert data["keyword_index"]["蔬菜"][0]["level1"] == "种植业"
    assert data["keyword_index"]["蔬菜"][0]["level2"] == "蔬菜作物"
    assert data["keyword_index"]["蔬菜"][0]["level3"] == "叶菜类"


def test_load_category_rules_from_json_restores_category_rules(tmp_path):
    excel_path = tmp_path / "category.xlsx"
    json_path = tmp_path / "category_rules.json"
    build_category_file(excel_path)
    build_category_rule_json(excel_path, json_path)

    rules = load_category_rules_from_json(json_path)
    index = load_category_rule_index(json_path)

    assert len(rules) == 3
    assert rules[0].level1 == "种植业"
    assert rules[0].level2 == "蔬菜作物"
    assert rules[0].level3 == "叶菜类"
    assert rules[0].module_name == "全品类"
    assert rules[0].keywords == ["白菜", "菠菜", "蔬菜"]
    assert index["keyword_index"]["净菜"][0]["level2"] == "农副食品加工"


def test_load_category_rules_from_config_builds_missing_json_from_excel(tmp_path, monkeypatch):
    excel_path = tmp_path / "category.xlsx"
    json_path = tmp_path / "generated" / "category_rules.json"
    build_category_file(excel_path)
    monkeypatch.setenv("CATEGORY_RULES_EXCEL_PATH", str(excel_path))
    monkeypatch.setenv("CATEGORY_RULES_JSON_PATH", str(json_path))

    rules = load_category_rules_from_config()

    assert json_path.exists()
    assert len(rules) == 3
    assert rules[0].level2 == "蔬菜作物"


def test_load_category_rules_from_config_rebuilds_empty_json_from_excel(tmp_path, monkeypatch):
    excel_path = tmp_path / "category.xlsx"
    json_path = tmp_path / "category_rules.json"
    build_category_file(excel_path)
    json_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("CATEGORY_RULES_EXCEL_PATH", str(excel_path))
    monkeypatch.setenv("CATEGORY_RULES_JSON_PATH", str(json_path))

    rules = load_category_rules_from_config()

    assert len(rules) == 3
    assert "category_tree" in load_category_rule_index(json_path)


def test_load_category_rules_from_config_rebuilds_invalid_json_from_excel(tmp_path, monkeypatch):
    excel_path = tmp_path / "category.xlsx"
    json_path = tmp_path / "category_rules.json"
    build_category_file(excel_path)
    json_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("CATEGORY_RULES_EXCEL_PATH", str(excel_path))
    monkeypatch.setenv("CATEGORY_RULES_JSON_PATH", str(json_path))

    rules = load_category_rules_from_config()

    assert len(rules) == 3
    assert load_category_rule_index(json_path)["version"] == 1
