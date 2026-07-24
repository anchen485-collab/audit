from app.company.provider import CompanyInfoProvider
from app.core.models import CompanyInfo


DEFAULT_COMPANY_DATA = {
    "金川县雪梨果业开发有限责任公司": {
        "business_scope": "梨、水果种植、加工、销售；农产品初加工服务。",
        "status": "存续",
    },
    "黑龙江省佳莲种业有限公司": {
        "business_scope": "水稻、玉米、大豆种子繁育、加工、销售。",
        "status": "存续",
    },
}


class MockCompanyInfoProvider(CompanyInfoProvider):
    """企查查 API 未申请完成前，用本地数据模拟企业经营范围。"""

    def __init__(self, data: dict | None = None):
        self.data = data or DEFAULT_COMPANY_DATA

    def get_company_info(self, company_name: str) -> CompanyInfo:
        item = self.data.get(company_name)
        if not item:
            return CompanyInfo(
                query_name=company_name,
                company_name=company_name,
                business_scope="",
                status="",
                source="mock",
                success=False,
                error="mock 数据中未找到该企业",
            )
        return CompanyInfo(
            query_name=company_name,
            company_name=item.get("company_name", company_name),
            business_scope=item.get("business_scope", ""),
            status=item.get("status", ""),
            source="mock",
            success=True,
            raw=item,
        )
