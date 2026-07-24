import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.category.rule_index import build_category_rule_json


def main():
    """命令行工具：把内部分类表 Excel 生成 JSON 规则索引。"""
    parser = argparse.ArgumentParser(description="从内部分类表 Excel 生成 JSON 规则索引")
    parser.add_argument("--excel", required=True, help="内部分类表 Excel 路径")
    parser.add_argument("--json", required=True, help="输出 JSON 规则索引路径")
    args = parser.parse_args()

    data = build_category_rule_json(Path(args.excel), Path(args.json))
    print(f"已生成分类规则 JSON：{args.json}")
    print(f"规则数量：{len(data['rules'])}")
    print(f"关键词数量：{len(data['keyword_index'])}")


if __name__ == "__main__":
    main()
