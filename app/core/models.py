from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class EmployeeRecord:
    """员工录入 Excel 中的一行数据。"""

    row_number: int
    date: str
    name: str
    category: str
    subcategory: str
    company_raw: str
    stage: str = ""
    company_name: str = ""
    website_url: str = ""


@dataclass
class CategoryRule:
    """内部分类表中的一条可匹配规则。"""

    level1: str
    level2: str
    level3: str
    module_name: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class CompanyInfo:
    """企业外部信息，后续真实企查查 API 也转换成这个结构。"""

    query_name: str
    company_name: str
    business_scope: str
    status: str
    source: str
    success: bool
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditResult:
    """单条录入记录的审计结论。"""

    row_number: int
    employee_name: str
    original_category: str
    original_subcategory: str
    original_stage: str
    original_company: str
    cleaned_company: str
    status: str
    confidence: int
    company_name: str = ""
    company_status: str = ""
    business_scope: str = ""
    data_source: str = ""
    website_url: str = ""
    error_type: str = ""
    reason: str = ""
    suggestion: str = ""
    needs_review: bool = False


class AuditGraphState(TypedDict, total=False):
    """LangGraph 节点之间共享的状态。"""

    employee_file: str
    category_file: str
    output_dir: str
    job_id: str
    provider: Any
    records: list[EmployeeRecord]
    rules: list[CategoryRule]
    company_infos: dict[str, CompanyInfo]
    results: list[AuditResult]
    summary: dict[str, Any]
    output_path: str
    errors: list[str]
    steps: list[str]
    trace_id: str
    trace: list[dict[str, Any]]
