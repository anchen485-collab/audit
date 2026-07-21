from pathlib import Path

from app.company.cache import CompanyInfoCache
from app.company.provider import CompanyInfoProvider
from app.company.website_crawler import WebsiteCrawler
from app.core.models import CompanyInfo, EmployeeRecord


class WebsiteCompanyInfoProvider(CompanyInfoProvider):
    """从企业官网定向抓取外部证据文本。"""

    def __init__(self, crawler: WebsiteCrawler | None = None, cache_path: str | Path | None = None):
        self.crawler = crawler or WebsiteCrawler()
        self.cache = CompanyInfoCache(cache_path) if cache_path else None

    def get_company_info(self, company_name: str) -> CompanyInfo:
        return CompanyInfo(
            query_name=company_name,
            company_name=company_name,
            business_scope="",
            status="",
            source="website",
            success=False,
            error="官网模式需要企业官网链接",
        )

    def get_company_info_for_record(self, record: EmployeeRecord) -> CompanyInfo:
        if not record.website_url:
            return self._failed(record, "官网链接缺失")

        if self.cache:
            cached = self.cache.get(record.website_url)
            if cached:
                return cached

        crawl_result = self.crawler.crawl(record.website_url)
        if not crawl_result.success:
            info = self._failed(record, crawl_result.error, crawl_result)
            if self.cache:
                self.cache.set(record.website_url, info)
            return info

        info = CompanyInfo(
            query_name=record.company_name or record.company_raw,
            company_name=record.company_name or record.company_raw,
            business_scope=crawl_result.text,
            status="",
            source="website",
            success=True,
            raw={
                "website_url": record.website_url,
                "visited_urls": crawl_result.visited_urls,
            },
        )
        if self.cache:
            self.cache.set(record.website_url, info)
        return info

    def _failed(self, record: EmployeeRecord, error: str, crawl_result=None) -> CompanyInfo:
        return CompanyInfo(
            query_name=record.company_name or record.company_raw,
            company_name=record.company_name or record.company_raw,
            business_scope=getattr(crawl_result, "text", ""),
            status="",
            source="website",
            success=False,
            error=error,
            raw={
                "website_url": record.website_url,
                "visited_urls": getattr(crawl_result, "visited_urls", []),
            },
        )
