from app.company.factory import get_company_provider
from app.company.mock_provider import MockCompanyInfoProvider
from app.company.qichacha_provider import QichachaCompanyInfoProvider
from app.company.website_crawler import HybridWebsiteCrawler, WebsiteCrawler
from app.company.website_provider import WebsiteCompanyInfoProvider


def test_get_company_provider_can_switch_to_mock(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "mock")

    provider = get_company_provider()

    assert isinstance(provider, MockCompanyInfoProvider)


def test_get_company_provider_can_switch_to_qichacha(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "qichacha")

    provider = get_company_provider()

    assert isinstance(provider, QichachaCompanyInfoProvider)


def test_get_company_provider_can_switch_to_website(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "website")
    monkeypatch.delenv("WEBSITE_CRAWLER_ENGINE", raising=False)
    monkeypatch.setenv("WEBSITE_CRAWL_MAX_PAGES", "3")
    monkeypatch.setenv("WEBSITE_CRAWL_MAX_DEPTH", "2")
    monkeypatch.setenv("WEBSITE_CRAWL_TIMEOUT", "6")

    provider = get_company_provider()

    assert isinstance(provider, WebsiteCompanyInfoProvider)
    assert isinstance(provider.crawler, HybridWebsiteCrawler)
    assert provider.crawler.max_pages == 3
    assert provider.crawler.max_depth == 2
    assert provider.crawler.timeout == 6


def test_get_company_provider_can_switch_to_hybrid_website_crawler(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "website")
    monkeypatch.setenv("WEBSITE_CRAWLER_ENGINE", "hybrid")
    monkeypatch.setenv("WEBSITE_CRAWL_MAX_PAGES", "3")
    monkeypatch.setenv("WEBSITE_CRAWL_MAX_DEPTH", "2")
    monkeypatch.setenv("WEBSITE_CRAWL_TIMEOUT", "6")

    provider = get_company_provider()

    assert isinstance(provider, WebsiteCompanyInfoProvider)
    assert isinstance(provider.crawler, HybridWebsiteCrawler)
    assert provider.crawler.max_pages == 3
    assert provider.crawler.max_depth == 2
    assert provider.crawler.timeout == 6


def test_get_company_provider_can_force_requests_website_crawler(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "website")
    monkeypatch.setenv("WEBSITE_CRAWLER_ENGINE", "requests")

    provider = get_company_provider()

    assert isinstance(provider, WebsiteCompanyInfoProvider)
    assert isinstance(provider.crawler, WebsiteCrawler)
