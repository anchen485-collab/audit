from app.companies.crawlers.website import WebsiteCrawler


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


def test_website_crawler_finds_about_page_under_learn_more_menu():
    pages = {
        "https://demo.com": """
            <html><body>
              <nav>
                <a href="/learn-more">了解更多</a>
              </nav>
            </body></html>
        """,
        "https://demo.com/learn-more": """
            <html><body>
              <nav>
                <a href="/learn-more/about-landbond">关于联邦</a>
                <a href="/learn-more/news">新闻动态</a>
              </nav>
            </body></html>
        """,
        "https://demo.com/learn-more/about-landbond": """
            <html><body>
              <div>首页 &gt; 了解更多 &gt; 关于我们</div>
              <h1>联邦家私</h1>
              <p>成立于1984年，提供一站到家的生活美学全案交付服务。</p>
            </body></html>
        """,
    }
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=6, max_depth=3, min_text_length=10)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert "一站到家的生活美学全案交付服务" in result.text
    assert "https://demo.com/learn-more/about-landbond" in result.visited_urls
    assert "https://demo.com/learn-more/news" not in visited


def test_website_crawler_ignores_footer_links_when_discovering_candidates():
    pages = {
        "https://demo.com": """
            <html><body>
              <main>
                <a href="/learn-more">了解更多</a>
              </main>
              <footer>
                <a href="/footer/about">关于联邦</a>
                <a href="/stores">所有门店</a>
                <a href="/materials">素材中心</a>
              </footer>
            </body></html>
        """,
        "https://demo.com/learn-more": """
            <html><body>
              <a href="/learn-more/about-landbond">关于联邦</a>
            </body></html>
        """,
        "https://demo.com/learn-more/about-landbond": """
            <html><body>
              <h1>关于我们</h1>
              <p>公司专注家居产品研发、制造和销售。</p>
            </body></html>
        """,
    }
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        return FakeResponse(pages[url])

    crawler = WebsiteCrawler(http_get=fake_get, max_pages=6, max_depth=3, min_text_length=10)

    result = crawler.crawl("https://demo.com")

    assert result.success is True
    assert "家居产品研发、制造和销售" in result.text
    assert "https://demo.com/footer/about" not in visited
    assert "https://demo.com/stores" not in visited
    assert "https://demo.com/materials" not in visited
