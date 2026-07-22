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
            text="首页 联系我们 公司简介 业务领域 蔬菜种植、加工、销售。",
            visited_urls=["https://demo.com"],
        )
    )
    provider = WebsiteCompanyInfoProvider(crawler=crawler)

    info = provider.get_company_info_for_record(build_record())

    assert info.success is True
    assert info.source == "website"
    assert "蔬菜种植、加工、销售" in info.business_scope
    assert "联系我们" not in info.business_scope
    assert info.raw["website_url"] == "https://demo.com"
    assert info.raw["raw_crawl_text"]
    assert info.raw["cleaning"]["cleaned_length"] > 0


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


def test_website_provider_recleans_stale_cache_before_returning(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    cache_path.write_text(
        """
        {
          "https://demo.com": {
            "query_name": "陕西汇生源生态农业有限公司",
            "company_name": "陕西汇生源生态农业有限公司",
            "business_scope": "首页 联系我们 产品品类 香甜软糯 公司简介 主营蔬菜种植、加工、销售。",
            "status": "",
            "source": "website",
            "success": true,
            "error": "",
            "raw": {
              "website_url": "https://demo.com",
              "visited_urls": ["https://demo.com"]
            }
          }
        }
        """,
        encoding="utf-8",
    )
    crawler = FakeCrawler(WebsiteCrawlResult(success=True, url="https://demo.com", text="不应该重新爬取", visited_urls=[]))
    provider = WebsiteCompanyInfoProvider(crawler=crawler, cache_path=cache_path)

    info = provider.get_company_info_for_record(build_record())

    assert crawler.urls == []
    assert "主营蔬菜种植、加工、销售" in info.business_scope
    assert "联系我们" not in info.business_scope
    assert info.raw["cleaning"]["version"] == provider.text_cleaner.CLEANING_VERSION


def test_website_provider_ignores_failed_cache_and_recrawls(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    cache_path.write_text(
        """
        {
          "https://demo.com": {
            "query_name": "陕西汇生源生态农业有限公司",
            "company_name": "陕西汇生源生态农业有限公司",
            "business_scope": "",
            "status": "",
            "source": "website",
            "success": false,
            "error": "官网无法访问：HTTP 404",
            "raw": {
              "website_url": "https://demo.com",
              "visited_urls": []
            }
          }
        }
        """,
        encoding="utf-8",
    )
    crawler = FakeCrawler(
        WebsiteCrawlResult(
            success=True,
            url="https://demo.com",
            text="公司简介 主营蔬菜种植、加工、销售。",
            visited_urls=["https://demo.com"],
        )
    )
    provider = WebsiteCompanyInfoProvider(crawler=crawler, cache_path=cache_path)

    info = provider.get_company_info_for_record(build_record())
    second = provider.get_company_info_for_record(build_record())

    assert info.success is True
    assert second.success is True
    assert crawler.urls == ["https://demo.com"]
    assert "蔬菜种植、加工、销售" in info.business_scope


def test_website_provider_recleans_empty_success_cache_with_raw_text(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    cache_path.write_text(
        """
        {
          "https://demo.com": {
            "query_name": "百和仕展示科技有限公司",
            "company_name": "百和仕展示科技有限公司",
            "business_scope": "",
            "status": "",
            "source": "website",
            "success": true,
            "error": "",
            "raw": {
              "website_url": "https://demo.com",
              "visited_urls": ["https://demo.com"],
              "raw_crawl_text": "百和仕BHS-全球商业空间一站式服务商 品牌终端商业空间体验升级，覆盖门店陈列、终端展示和品牌体验空间。",
              "cleaning": {
                "version": 4,
                "cleaned_length": 0
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )
    crawler = FakeCrawler(WebsiteCrawlResult(success=True, url="https://demo.com", text="不应该重新爬取", visited_urls=[]))
    provider = WebsiteCompanyInfoProvider(crawler=crawler, cache_path=cache_path)

    info = provider.get_company_info_for_record(build_record())

    assert crawler.urls == []
    assert "商业空间体验升级" in info.business_scope
    assert info.raw["cleaning"]["version"] == provider.text_cleaner.CLEANING_VERSION
    assert info.raw["cleaning"]["mode"] == "fallback"


def test_website_provider_marks_empty_cleaned_text_as_failed(tmp_path):
    crawler = FakeCrawler(
        WebsiteCrawlResult(
            success=True,
            url="https://demo.com",
            text="网站系统更新维护中 品牌官方网站正在升级中，敬请期待……",
            visited_urls=["https://demo.com"],
        )
    )
    provider = WebsiteCompanyInfoProvider(crawler=crawler, cache_path=tmp_path / "website_cache.json")

    info = provider.get_company_info_for_record(build_record())
    second = provider.get_company_info_for_record(build_record())

    assert info.success is False
    assert info.error == "官网文本清洗后无有效业务证据"
    assert info.raw["raw_crawl_text"]
    assert info.raw["cleaning"]["mode"] == "fallback"
    assert crawler.urls == ["https://demo.com", "https://demo.com"]
    assert second.success is False
