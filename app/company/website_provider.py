import logging
from pathlib import Path

from app.company.cache import CompanyInfoCache
from app.company.provider import CompanyInfoProvider
from app.company.website_crawler import WebsiteCrawler
from app.core.models import CompanyInfo, EmployeeRecord


logger = logging.getLogger(__name__)


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
            logger.warning("website_provider_missing_url 官网链接缺失 company=%s row=%s", record.company_raw, record.row_number)
            return self._failed(record, "官网链接缺失")

        if self.cache:
            cached = self.cache.get(record.website_url)
            if cached:
                logger.info("website_provider_cache_hit 官网缓存命中 company=%s url=%s", record.company_raw, record.website_url)
                return cached

        logger.info("website_provider_crawl_start 开始从官网获取企业信息 company=%s url=%s", record.company_raw, record.website_url)
        crawl_result = self.crawler.crawl(record.website_url)
        if not crawl_result.success:
            logger.warning(
                "website_provider_crawl_failed 官网企业信息获取失败 company=%s url=%s error=%s visited_count=%s",
                record.company_raw,
                record.website_url,
                crawl_result.error,
                len(crawl_result.visited_urls),
            )
            info = self._failed(record, crawl_result.error, crawl_result)
            if self.cache:
                self.cache.set(record.website_url, info)
            return info

        logger.info(
            "website_provider_crawl_success 官网企业信息获取成功 company=%s url=%s visited_count=%s text_length=%s",
            record.company_raw,
            record.website_url,
            len(crawl_result.visited_urls),
            len(crawl_result.text or ""),
        )
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
