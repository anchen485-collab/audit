import os

from app.company.mock_provider import MockCompanyInfoProvider
from app.company.provider import CompanyInfoProvider
from app.company.qichacha_provider import QichachaCompanyInfoProvider
from app.core.config import load_env_file


def get_company_provider() -> CompanyInfoProvider:
    """根据 .env 中的 COMPANY_PROVIDER 选择企业信息来源。"""
    load_env_file()
    provider_name = os.getenv("COMPANY_PROVIDER", "mock").strip().lower()
    if provider_name == "qichacha":
        return QichachaCompanyInfoProvider()
    return MockCompanyInfoProvider()
