import os
import logging
from pathlib import Path

from app.companies.providers.mock import MockCompanyInfoProvider
from app.companies.providers.base import CompanyInfoProvider
from app.companies.providers.qichacha import QichachaCompanyInfoProvider
from app.companies.crawlers.website import Crawl4AIWebsiteCrawler, HybridWebsiteCrawler, WebsiteCrawler
from app.companies.providers.website import WebsiteCompanyInfoProvider
from app.core.config import ensure_storage_dirs, load_env_file


logger = logging.getLogger(__name__)


def get_company_provider() -> CompanyInfoProvider:
    """根据 .env 中的 COMPANY_PROVIDER 选择企业信息来源。"""
    load_env_file()
    provider_name = os.getenv("COMPANY_PROVIDER", "mock").strip().lower()
    logger.info("company_provider_select 企业信息源选择 provider=%s", provider_name)
    if provider_name == "website":
        paths = ensure_storage_dirs()
        crawler = _build_website_crawler()
        cache_path = Path(os.getenv("WEBSITE_CACHE_PATH") or paths["cache"] / "website_cache.json")
        logger.info(
            "company_provider_website_ready 官网信息源已就绪 crawler=%s max_pages=%s max_depth=%s timeout=%s cache_path=%s",
            crawler.__class__.__name__,
            crawler.max_pages,
            crawler.max_depth,
            crawler.timeout,
            cache_path,
        )
        return WebsiteCompanyInfoProvider(crawler=crawler, cache_path=cache_path)
    if provider_name == "qichacha":
        return QichachaCompanyInfoProvider()
    return MockCompanyInfoProvider()


def _build_website_crawler():
    max_pages = int(os.getenv("WEBSITE_CRAWL_MAX_PAGES", "8"))
    max_depth = int(os.getenv("WEBSITE_CRAWL_MAX_DEPTH", "3"))
    timeout = int(os.getenv("WEBSITE_CRAWL_TIMEOUT", "8"))
    engine = os.getenv("WEBSITE_CRAWLER_ENGINE", "hybrid").strip().lower()

    if engine == "crawl4ai":
        return Crawl4AIWebsiteCrawler(max_pages=max_pages, max_depth=max_depth, timeout=timeout)
    if engine == "hybrid":
        return HybridWebsiteCrawler(
            primary=WebsiteCrawler(max_pages=max_pages, max_depth=max_depth, timeout=timeout),
            fallback=Crawl4AIWebsiteCrawler(max_pages=max_pages, max_depth=max_depth, timeout=timeout),
        )
    if engine != "requests":
        logger.warning("company_provider_unknown_crawler_engine 未知官网爬虫引擎 engine=%s，回退 requests", engine)
    return WebsiteCrawler(max_pages=max_pages, max_depth=max_depth, timeout=timeout)

