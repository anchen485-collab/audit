from app.companies.crawlers.website import HybridWebsiteCrawler, WebsiteCrawlResult


class FakeCrawler:
    def __init__(self, result):
        self.result = result
        self.urls = []
        self.max_pages = 4
        self.max_depth = 2
        self.timeout = 8
        self.min_text_length = 20
        self.max_text_length = 12000

    def crawl(self, url):
        self.urls.append(url)
        return self.result


def test_hybrid_website_crawler_uses_primary_success_without_fallback():
    primary = FakeCrawler(WebsiteCrawlResult(success=True, url="https://demo.com", text="业务领域 蔬菜种植。"))
    fallback = FakeCrawler(WebsiteCrawlResult(success=True, url="https://demo.com", text="不应该使用"))
    crawler = HybridWebsiteCrawler(primary=primary, fallback=fallback)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert result.text == "业务领域 蔬菜种植。"
    assert primary.urls == ["https://demo.com"]
    assert fallback.urls == []


def test_hybrid_website_crawler_falls_back_when_primary_has_insufficient_evidence():
    primary = FakeCrawler(
        WebsiteCrawlResult(
            success=False,
            url="https://demo.com",
            text="短",
            visited_urls=["https://demo.com"],
            error="官网证据不足",
        )
    )
    fallback = FakeCrawler(
        WebsiteCrawlResult(
            success=True,
            url="https://demo.com",
            text="公司简介 主营蔬菜种植、加工、销售。",
            visited_urls=["https://demo.com", "https://demo.com/about"],
        )
    )
    crawler = HybridWebsiteCrawler(primary=primary, fallback=fallback)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert "蔬菜种植、加工、销售" in result.text
    assert fallback.urls == ["https://demo.com"]
    assert result.visited_urls == ["https://demo.com", "https://demo.com/about"]


def test_hybrid_website_crawler_preserves_invalid_url_without_fallback():
    primary = FakeCrawler(WebsiteCrawlResult(success=False, url="", error="官网链接格式异常"))
    fallback = FakeCrawler(WebsiteCrawlResult(success=True, url="https://demo.com", text="不应该使用"))
    crawler = HybridWebsiteCrawler(primary=primary, fallback=fallback)

    result = crawler.crawl("")

    assert result.success is False
    assert result.error == "官网链接格式异常"
    assert fallback.urls == []


def test_hybrid_website_crawler_combines_errors_when_fallback_also_fails():
    primary = FakeCrawler(WebsiteCrawlResult(success=False, url="https://demo.com", error="官网证据不足"))
    fallback = FakeCrawler(WebsiteCrawlResult(success=False, url="https://demo.com", error="Crawl4AI 未安装或未完成浏览器初始化"))
    crawler = HybridWebsiteCrawler(primary=primary, fallback=fallback)

    result = crawler.crawl("https://demo.com")

    assert result.success is False
    assert result.error == "官网证据不足；Crawl4AI 兜底失败：Crawl4AI 未安装或未完成浏览器初始化"
