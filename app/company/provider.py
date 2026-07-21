from abc import ABC, abstractmethod

from app.core.models import CompanyInfo


class CompanyInfoProvider(ABC):
    """企业信息查询接口，方便后续从 mock 切换到企查查官方 API。"""

    @abstractmethod
    def get_company_info(self, company_name: str) -> CompanyInfo:
        """根据企业名称查询企业信息。"""
