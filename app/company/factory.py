import os
from pathlib import Path

from app.company.mock_provider import MockCompanyInfoProvider
from app.company.provider import CompanyInfoProvider
from app.company.qichacha_provider import QichachaCompanyInfoProvider
from app.company.website_crawler import WebsiteCrawler
from app.company.website_provider import WebsiteCompanyInfoProvider
from app.core.config import ensure_storage_dirs, load_env_file


def get_company_provider() -> CompanyInfoProvider:
    """根据 .env 中的 COMPANY_PROVIDER 选择企业信息来源。"""
    load_env_file()
    provider_name = os.getenv("COMPANY_PROVIDER", "mock").strip().lower()
    if provider_name == "website":
        paths = ensure_storage_dirs()
        crawler = WebsiteCrawler(
            max_pages=int(os.getenv("WEBSITE_CRAWL_MAX_PAGES", "4")),
            timeout=int(os.getenv("WEBSITE_CRAWL_TIMEOUT", "8")),
        )
        cache_path = Path(os.getenv("WEBSITE_CACHE_PATH", paths["cache"] / "website_cache.json"))
        return WebsiteCompanyInfoProvider(crawler=crawler, cache_path=cache_path)
    if provider_name == "qichacha":
        return QichachaCompanyInfoProvider()
    return MockCompanyInfoProvider()
