from __future__ import annotations

from dataclasses import dataclass, field
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests


TARGET_MODULES = {
    "业务领域": ["业务领域", "业务范围", "主营业务", "产品服务", "产品中心", "服务领域"],
    "公司简介": ["公司简介", "企业简介", "关于我们", "公司介绍", "走进我们"],
    "经典案例": ["经典案例", "客户案例", "成功案例", "案例展示", "项目案例"],
}
IGNORED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
    ".mp4",
    ".avi",
)


@dataclass
class WebsiteCrawlResult:
    """官网爬取结果。"""

    success: bool
    url: str
    text: str = ""
    visited_urls: list[str] = field(default_factory=list)
    error: str = ""


class WebsiteCrawler:
    """只爬取官网首页和指定高价值模块页面。"""

    def __init__(
        self,
        http_get=None,
        max_pages: int = 4,
        timeout: int = 8,
        min_text_length: int = 20,
        max_text_length: int = 12000,
    ):
        self.http_get = http_get or requests.get
        self.max_pages = max_pages
        self.timeout = timeout
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length

    def crawl(self, url: str) -> WebsiteCrawlResult:
        """爬取官网首页和公司简介/经典案例/业务领域页面。"""
        normalized_url = self._normalize_start_url(url)
        if not normalized_url:
            return WebsiteCrawlResult(success=False, url=url, error="官网链接格式异常")

        try:
            home_html = self._fetch(normalized_url)
        except Exception as exc:
            return WebsiteCrawlResult(success=False, url=normalized_url, error=f"官网无法访问：{exc}")

        home_text = self.extract_text(home_html)
        target_links = self.extract_target_links(normalized_url, home_html)
        urls = list(dict.fromkeys([normalized_url] + target_links))[: self.max_pages]

        texts = [home_text]
        visited = [normalized_url]
        for page_url in urls[1:]:
            try:
                texts.append(self.extract_text(self._fetch(page_url)))
                visited.append(page_url)
            except Exception:
                continue

        text = self._compact_text(" ".join(texts))[: self.max_text_length]
        if len(text) < self.min_text_length:
            return WebsiteCrawlResult(success=False, url=normalized_url, text=text, visited_urls=visited, error="官网证据不足")
        return WebsiteCrawlResult(success=True, url=normalized_url, text=text, visited_urls=visited)

    def extract_target_links(self, base_url: str, html: str) -> list[str]:
        """从首页中筛选目标模块链接，按业务领域、公司简介、经典案例排序。"""
        soup = BeautifulSoup(html, "html.parser")
        candidates: dict[str, tuple[int, str]] = {}
        base_domain = urlparse(base_url).netloc
        priority_index = {name: index for index, name in enumerate(TARGET_MODULES)}

        for link in soup.find_all("a"):
            href = (link.get("href") or "").strip()
            label = self._compact_text(link.get_text(" ", strip=True))
            absolute_url = urljoin(base_url, href)
            if not self._is_allowed_link(absolute_url, base_domain):
                continue
            priority = self._link_priority(label, absolute_url, priority_index)
            if priority is None:
                continue
            if absolute_url not in candidates or priority < candidates[absolute_url][0]:
                candidates[absolute_url] = (priority, absolute_url)

        ordered = sorted(candidates.values(), key=lambda item: item[0])
        return [url for _, url in ordered]

    def extract_text(self, html: str) -> str:
        """清洗 HTML 并提取可用于规则匹配的正文文本。"""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "a"]):
            tag.extract()
        return self._compact_text(soup.get_text(" ", strip=True))

    def _fetch(self, url: str) -> str:
        response = self.http_get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "audit-agent/1.0"},
        )
        if response.status_code >= 400:
            raise requests.RequestException(f"HTTP {response.status_code}")
        if getattr(response, "encoding", None) is None:
            response.encoding = "utf-8"
        return response.text

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _normalize_start_url(url: str) -> str:
        value = (url or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            value = "https://" + value
        parsed = urlparse(value)
        if not parsed.netloc:
            return ""
        return value.rstrip("/")

    @staticmethod
    def _is_allowed_link(url: str, base_domain: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.netloc != base_domain:
            return False
        return not parsed.path.lower().endswith(IGNORED_EXTENSIONS)

    @staticmethod
    def _link_priority(label: str, url: str, priority_index: dict[str, int]) -> int | None:
        text = f"{label} {url}".lower()
        best: int | None = None
        for module_name, words in TARGET_MODULES.items():
            for word in words:
                if word.lower() in text:
                    priority = priority_index[module_name]
                    if best is None or priority < best:
                        best = priority
        return best
