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


class FakeEncodedResponse:
    def __init__(self, content, encoding, apparent_encoding):
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self.status_code = 200

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")


def test_website_crawler_decodes_utf8_page_when_header_encoding_is_wrong():
    html = "<html><body><p>黑龙江德玉种业有限公司主营玉米等农作物制种。</p></body></html>"
    response = FakeEncodedResponse(
        content=html.encode("utf-8"),
        encoding="ISO-8859-1",
        apparent_encoding="utf-8",
    )
    crawler = WebsiteCrawler(http_get=lambda url, timeout, headers: response)

    fetched_html = crawler._fetch("https://demo.com")

    assert "黑龙江德玉种业有限公司" in fetched_html
    assert "é»" not in fetched_html


def test_website_crawler_repairs_utf8_text_decoded_as_gb18030_mojibake():
    html = "<html><body><p>图索科技（上海）有限公司 From Source to Sea Protection and restoration of fish migration in river</p></body></html>"
    response = FakeEncodedResponse(
        content=html.encode("utf-8"),
        encoding="gb18030",
        apparent_encoding="gb18030",
    )
    crawler = WebsiteCrawler(http_get=lambda url, timeout, headers: response)

    fetched_html = crawler._fetch("https://demo.com")

    assert "图索科技（上海）有限公司" in fetched_html
    assert "鍥剧储绉戞妧" not in fetched_html


def test_website_crawler_repairs_mojibake_when_extracting_text():
    html = "<html><body><p>图索科技（上海）有限公司 From Source to Sea</p></body></html>"
    mojibake_html = html.encode("utf-8").decode("gb18030", errors="replace")

    text = WebsiteCrawler().extract_text(mojibake_html)

    assert "图索科技（上海）有限公司" in text
    assert "鍥剧储绉戞妧" not in text


def test_website_crawler_uses_browser_headers_and_retries_https_after_403():
    calls = []

    def fake_get(url, timeout, headers):
        calls.append((url, headers))
        if url.startswith("http://"):
            return FakeResponse("forbidden", status_code=403)
        return FakeResponse("<html><body><p>公司简介 主营蔬菜种植、加工、销售。</p></body></html>")

    crawler = WebsiteCrawler(http_get=fake_get)

    fetched_html = crawler._fetch("http://demo.com/col.jsp?id=109")

    assert "主营蔬菜种植" in fetched_html
    assert calls[0][0] == "http://demo.com/col.jsp?id=109"
    assert calls[1][0] == "https://demo.com/col.jsp?id=109"
    assert "Mozilla/5.0" in calls[0][1]["User-Agent"]
    assert calls[0][1]["Referer"] == "http://demo.com/"


def test_website_crawler_retries_site_root_when_start_path_returns_404():
    visited = []

    def fake_get(url, timeout, headers):
        visited.append(url)
        if url == "https://demo.com/zh-hans":
            return FakeResponse("missing", status_code=404)
        return FakeResponse("<html><body><p>公司简介 主营水产育苗、养殖和水产品加工。</p></body></html>")

    crawler = WebsiteCrawler(http_get=fake_get, min_text_length=10)

    result = crawler.crawl("https://demo.com/zh-hans")

    assert result.success is True
    assert visited == ["https://demo.com/zh-hans", "https://demo.com"]
    assert result.visited_urls == ["https://demo.com"]
    assert "水产育苗" in result.text
