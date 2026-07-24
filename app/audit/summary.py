from collections import defaultdict

from app.core.models import AuditResult


def build_person_summary(results: list[AuditResult]) -> list[dict]:
    """按人员汇总录入数量和质量指标。"""
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "姓名": "",
            "录入数量": 0,
            "完整数量": 0,
            "正确数量": 0,
            "错误数量": 0,
            "疑似错误数量": 0,
            "无法判断数量": 0,
            "正确率": "0%",
        }
    )
    for result in results:
        item = grouped[result.employee_name]
        item["姓名"] = result.employee_name
        item["录入数量"] += 1
        if result.status != "信息缺失":
            item["完整数量"] += 1
        if result.status == "正确":
            item["正确数量"] += 1
        elif result.status == "错误":
            item["错误数量"] += 1
        elif result.status == "疑似错误":
            item["疑似错误数量"] += 1
        elif result.status == "无法判断":
            item["无法判断数量"] += 1

    for item in grouped.values():
        auto_total = item["正确数量"] + item["错误数量"]
        if auto_total:
            item["正确率"] = f"{item['正确数量'] / auto_total:.0%}"
    return list(grouped.values())
