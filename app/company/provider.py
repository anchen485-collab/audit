from abc import ABC, abstractmethod

from app.core.models import CompanyInfo, EmployeeRecord


class CompanyInfoProvider(ABC):
    """企业信息查询接口，方便后续从 mock 切换到企查查官方 API。"""

    @abstractmethod
    def get_company_info(self, company_name: str) -> CompanyInfo:
        """根据企业名称查询企业信息。"""

    def get_company_info_for_record(self, record: EmployeeRecord) -> CompanyInfo:
        """默认按企业名称查询；官网 Provider 可覆写后读取整条记录。"""
        return self.get_company_info(record.company_name or record.company_raw)
