from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_category_rules_excel_path, get_category_rules_json_path
from app.core.models import CategoryRule
from app.excel.category_reader import read_category_rules


LOW_WEIGHT_MODULES = {"环节", "生态", "全生态"}
DEFAULT_KEYWORD_WEIGHT = 60
LOW_KEYWORD_WEIGHT = 10
logger = logging.getLogger(__name__)


def build_category_rule_json(excel_path: str | Path, json_path: str | Path) -> dict[str, Any]:
    """把业务维护的分类 Excel 转换成运行时使用的 JSON 规则索引。"""
    rules = read_category_rules(excel_path)
    data = build_category_rule_index(rules, source_file=str(excel_path))
    output_path = Path(json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def build_category_rule_index(rules: list[CategoryRule], source_file: str = "") -> dict[str, Any]:
    """根据规则列表构建树形分类和关键词倒排索引。"""
    data: dict[str, Any] = {
        "version": 1,
        "source_file": source_file,
        "rules": [],
        "category_tree": {},
        "keyword_index": {},
    }
    for rule in rules:
        rule_item = _rule_to_dict(rule)
        data["rules"].append(rule_item)
        _append_to_tree(data["category_tree"], rule)
        _append_to_keyword_index(data["keyword_index"], rule)
    return data


def load_category_rule_index(json_path: str | Path) -> dict[str, Any]:
    """读取 JSON 规则索引，并做最基础的格式校验。"""
    path = Path(json_path)
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise ValueError(f"分类规则 JSON 文件为空：{path}")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"分类规则 JSON 不是合法 JSON：{path}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("分类规则 JSON 格式不正确或版本不支持")
    if not isinstance(data.get("rules"), list):
        raise ValueError("分类规则 JSON 缺少 rules 列表")
    return data


def load_category_rules_from_json(json_path: str | Path) -> list[CategoryRule]:
    """从 JSON 规则索引还原为现有审计流程使用的 CategoryRule 列表。"""
    data = load_category_rule_index(json_path)
    return [
        CategoryRule(
            level1=str(item.get("level1", "")),
            level2=str(item.get("level2", "")),
            level3=str(item.get("level3", "")),
            module_name=str(item.get("module_name", "")),
            keywords=[str(keyword) for keyword in item.get("keywords", []) if str(keyword)],
        )
        for item in data["rules"]
    ]


def load_category_rules_from_config(category_source: str | Path | None = None) -> list[CategoryRule]:
    """按配置加载分类规则；兼容旧的 Excel 分类表路径。"""
    if category_source:
        source_path = Path(category_source)
        if source_path.suffix.lower() == ".json":
            return load_category_rules_from_json(source_path)
        return read_category_rules(source_path)

    json_path = get_category_rules_json_path()
    if json_path.exists():
        try:
            return load_category_rules_from_json(json_path)
        except ValueError as exc:
            excel_path = get_category_rules_excel_path()
            if excel_path and excel_path.exists():
                logger.warning(
                    "category_rules_json_invalid 分类规则 JSON 不可用，将从 Excel 重新生成 json_path=%s excel_path=%s error=%s",
                    json_path,
                    excel_path,
                    exc,
                )
                build_category_rule_json(excel_path, json_path)
                return load_category_rules_from_json(json_path)
            raise

    excel_path = get_category_rules_excel_path()
    if excel_path and excel_path.exists():
        build_category_rule_json(excel_path, json_path)
        return load_category_rules_from_json(json_path)

    raise ValueError(
        "分类规则 JSON 文件不存在。请先配置 CATEGORY_RULES_JSON_PATH，"
        "或配置 CATEGORY_RULES_EXCEL_PATH 让系统从分类表 Excel 自动生成。"
    )


def _rule_to_dict(rule: CategoryRule) -> dict[str, Any]:
    return {
        "level1": rule.level1,
        "level2": rule.level2,
        "level3": rule.level3,
        "module_name": rule.module_name,
        "keywords": rule.keywords,
    }


def _append_to_tree(tree: dict[str, Any], rule: CategoryRule) -> None:
    level1_node = tree.setdefault(rule.level1, {})
    level2_node = level1_node.setdefault(rule.level2, {})
    level3_node = level2_node.setdefault(rule.level3, {"modules": {}})
    level3_node["modules"][rule.module_name] = rule.keywords


def _append_to_keyword_index(keyword_index: dict[str, list[dict[str, Any]]], rule: CategoryRule) -> None:
    weight = LOW_KEYWORD_WEIGHT if rule.module_name in LOW_WEIGHT_MODULES else DEFAULT_KEYWORD_WEIGHT
    for keyword in rule.keywords:
        if not keyword:
            continue
        keyword_index.setdefault(keyword, []).append(
            {
                "level1": rule.level1,
                "level2": rule.level2,
                "level3": rule.level3,
                "module": rule.module_name,
                "weight": weight,
            }
        )
