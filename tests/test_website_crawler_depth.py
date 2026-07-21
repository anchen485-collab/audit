from app.company.website_crawler import WebsiteCrawler


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"


def test_website_crawler_finds_target_pages_from_second_and_third_level_links():
    pages = {
        "https://demo.com": """
            <html><body>
              <h1>首页</h1>
              <a href="/about">关于我们</a>
              <a href="/solution">解决方案</a>
            </body></html>
        """,
        "https://demo.com/about": """
            <html><body>
              <h1>关于我们</h1>
              <a href="/about/profile">公司简介</a>
            </body></html>
        """,
        "https://demo.com/about/profile": "<html><body><h1>公司简介</h1><p>公司专注蔬菜种植。</p></body></html>",
        "https://demo.com/solution": """
            <html><body>
              <h1>解决方案</h1>
              <a href="/solution/agri">农业方案</a>
            </body></html>
        """,
        "https://demo.com/solution/agri": """
            <html><body>
              <h1>农业方案</h1>
              <a href="/solution/agri/business">业务领域</a>
            </body></html>
        """,
        "https://demo.com/solution/agri/business": "<html><body><h1>业务领域</h1><p>蔬菜加工、销售、配送。</p></body></html>",
    }
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=8, max_depth=3, min_text_length=10)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert "公司专注蔬菜种植" in result.text
    assert "蔬菜加工、销售、配送" in result.text
    assert "https://demo.com/about/profile" in result.visited_urls
    assert "https://demo.com/solution/agri/business" in result.visited_urls


def test_website_crawler_respects_max_depth_limit():
    pages = {
        "https://demo.com": '<html><body><a href="/level1">关于我们</a></body></html>',
        "https://demo.com/level1": '<html><body><a href="/level1/profile">公司简介</a></body></html>',
        "https://demo.com/level1/profile": "<html><body><p>公司简介深层文本</p></body></html>",
    }
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=8, max_depth=1, min_text_length=1)

    result = crawler.crawl("https://demo.com")

    assert result.success is False
    assert result.error == "官网证据不足"
    assert "https://demo.com/level1/profile" not in visited
    assert "深层文本" not in result.text
