from app.company.website_crawler import WebsiteCrawler


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"


def test_website_crawler_only_visits_target_module_pages_on_same_domain():
    pages = {
        "https://demo.com": """
            <html><body>
              <nav>导航内容</nav>
              <h1>首页</h1>
              <a href="/about">公司简介</a>
              <a href="/business">业务领域</a>
              <a href="/case">经典案例</a>
              <a href="/news">新闻资讯</a>
              <a href="https://other.com/about">外部关于</a>
            </body></html>
        """,
        "https://demo.com/about": "<html><body><h1>公司简介</h1><p>我们专注蔬菜种植。</p></body></html>",
        "https://demo.com/business": "<html><body><h1>业务领域</h1><p>蔬菜加工、销售、冷链配送。</p></body></html>",
        "https://demo.com/case": "<html><body><h1>经典案例</h1><p>服务大型农业基地。</p></body></html>",
    }
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=4, timeout=3)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert visited == [
        "https://demo.com",
        "https://demo.com/business",
        "https://demo.com/about",
        "https://demo.com/case",
    ]
    assert "蔬菜加工" in result.text
    assert "导航内容" not in result.text
    assert "新闻资讯" not in result.text


def test_website_crawler_reports_insufficient_text():
    def fake_get(url, timeout, headers):
        return FakeResponse("<html><body>短</body></html>")

    crawler = WebsiteCrawler(http_get=fake_get, min_text_length=20)

    result = crawler.crawl("https://demo.com")

    assert result.success is False
    assert result.error == "官网证据不足"
