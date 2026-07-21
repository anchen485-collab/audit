from app.company.website_crawler import WebsiteCrawlResult
from app.company.website_provider import WebsiteCompanyInfoProvider
from app.core.models import EmployeeRecord


class FakeCrawler:
    def __init__(self, result):
        self.result = result
        self.urls = []

    def crawl(self, url):
        self.urls.append(url)
        return self.result


def build_record(website_url="https://demo.com"):
    return EmployeeRecord(
        row_number=2,
        date="7月21日",
        name="张冰冰",
        category="种植业",
        subcategory="蔬菜作物",
        company_raw="陕西汇生源生态农业有限公司",
        stage="加工、销售",
        website_url=website_url,
    )


def test_website_provider_returns_company_info_from_crawled_text():
    crawler = FakeCrawler(
        WebsiteCrawlResult(
            success=True,
            url="https://demo.com",
            text="公司简介 业务领域 蔬菜种植、加工、销售。",
            visited_urls=["https://demo.com"],
        )
    )
    provider = WebsiteCompanyInfoProvider(crawler=crawler)

    info = provider.get_company_info_for_record(build_record())

    assert info.success is True
    assert info.source == "website"
    assert info.business_scope == "公司简介 业务领域 蔬菜种植、加工、销售。"
    assert info.raw["website_url"] == "https://demo.com"


def test_website_provider_returns_clear_error_when_url_missing():
    provider = WebsiteCompanyInfoProvider()

    info = provider.get_company_info_for_record(build_record(website_url=""))

    assert info.success is False
    assert info.error == "官网链接缺失"


def test_website_provider_uses_cache_for_repeated_url(tmp_path):
    crawler = FakeCrawler(
        WebsiteCrawlResult(
            success=True,
            url="https://demo.com",
            text="业务领域 蔬菜种植、加工、销售。",
            visited_urls=["https://demo.com"],
        )
    )
    provider = WebsiteCompanyInfoProvider(crawler=crawler, cache_path=tmp_path / "website_cache.json")

    first = provider.get_company_info_for_record(build_record())
    second = provider.get_company_info_for_record(build_record())

    assert first.success is True
    assert second.success is True
    assert crawler.urls == ["https://demo.com"]
