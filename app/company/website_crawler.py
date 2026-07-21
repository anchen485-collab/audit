from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests


logger = logging.getLogger(__name__)


TARGET_MODULES = {
    "业务领域": ["业务领域", "业务范围", "主营业务", "产品服务", "产品中心", "服务领域"],
    "公司简介": ["公司简介", "企业简介", "关于我们", "公司介绍", "走进我们"],
    "经典案例": ["经典案例", "客户案例", "成功案例", "案例展示", "项目案例"],
}
DISCOVERY_WORDS = [
    "关于",
    "简介",
    "公司",
    "业务",
    "领域",
    "案例",
    "方案",
    "解决方案",
    "产品",
    "服务",
    "项目",
]
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


@dataclass
class LinkCandidate:
    """待访问链接，depth 用来限制爬取深度。"""

    url: str
    depth: int
    is_target: bool
    priority: int


class WebsiteCrawler:
    """只爬取官网首页和指定高价值模块页面，支持有限深度发现。"""

    def __init__(
        self,
        http_get=None,
        max_pages: int = 4,
        max_depth: int = 2,
        timeout: int = 8,
        min_text_length: int = 20,
        max_text_length: int = 12000,
    ):
        self.http_get = http_get or requests.get
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.timeout = timeout
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length

    def crawl(self, url: str) -> WebsiteCrawlResult:
        """从官网首页开始，有限深度发现并抓取目标模块页面。"""
        normalized_url = self._normalize_start_url(url)
        if not normalized_url:
            logger.warning("website_crawl_invalid_url 官网链接格式异常 url=%s", url)
            return WebsiteCrawlResult(success=False, url=url, error="官网链接格式异常")

        logger.info(
            "website_crawl_start 官网爬取开始 url=%s max_pages=%s max_depth=%s timeout=%s",
            normalized_url,
            self.max_pages,
            self.max_depth,
            self.timeout,
        )
        base_domain = urlparse(normalized_url).netloc
        queue: deque[LinkCandidate] = deque([LinkCandidate(normalized_url, 0, True, 0)])
        queued = {normalized_url}
        visited: list[str] = []
        fetched_html: dict[str, str] = {}
        evidence_texts: list[str] = []

        while queue and len(visited) < self.max_pages:
            current = queue.popleft()
            if current.url in fetched_html:
                continue
            try:
                html = self._fetch(current.url)
            except Exception as exc:
                if not visited:
                    logger.warning("website_crawl_failed 官网首页无法访问 url=%s error=%s", normalized_url, exc)
                    return WebsiteCrawlResult(success=False, url=normalized_url, error=f"官网无法访问：{exc}")
                logger.warning("website_crawl_page_failed 官网页面访问失败 url=%s depth=%s error=%s", current.url, current.depth, exc)
                continue

            fetched_html[current.url] = html
            visited.append(current.url)
            logger.info(
                "website_crawl_page_success 官网页面访问成功 url=%s depth=%s is_target=%s",
                current.url,
                current.depth,
                current.is_target,
            )
            if current.is_target:
                evidence_texts.append(self.extract_text(html))

            if current.depth >= self.max_depth:
                continue

            candidates = self.extract_candidate_links(current.url, html, base_domain, current.depth + 1)
            logger.info(
                "website_crawl_candidates_found 官网候选链接发现 url=%s depth=%s candidate_count=%s",
                current.url,
                current.depth,
                len(candidates),
            )
            for candidate in candidates:
                if candidate.url in queued or candidate.url in fetched_html:
                    continue
                queued.add(candidate.url)
                queue.append(candidate)
            queue = deque(sorted(queue, key=lambda item: (not item.is_target, item.priority, item.depth)))

        text = self._compact_text(" ".join(evidence_texts))[: self.max_text_length]
        if len(text) < self.min_text_length:
            logger.warning(
                "website_crawl_insufficient_evidence 官网证据不足 url=%s visited_count=%s text_length=%s",
                normalized_url,
                len(visited),
                len(text),
            )
            return WebsiteCrawlResult(success=False, url=normalized_url, text=text, visited_urls=visited, error="官网证据不足")
        logger.info(
            "website_crawl_success 官网爬取成功 url=%s visited_count=%s text_length=%s",
            normalized_url,
            len(visited),
            len(text),
        )
        return WebsiteCrawlResult(success=True, url=normalized_url, text=text, visited_urls=visited)

    def extract_target_links(self, base_url: str, html: str) -> list[str]:
        """保留旧接口：返回当前页面中直接命中的目标模块链接。"""
        base_domain = urlparse(base_url).netloc
        candidates = self.extract_candidate_links(base_url, html, base_domain, 1)
        return [candidate.url for candidate in candidates if candidate.is_target]

    def extract_candidate_links(self, base_url: str, html: str, base_domain: str, depth: int) -> list[LinkCandidate]:
        """提取目标模块链接和可继续探索的中间栏目链接。"""
        soup = BeautifulSoup(html, "html.parser")
        candidates: dict[str, LinkCandidate] = {}
        priority_index = {name: index for index, name in enumerate(TARGET_MODULES)}

        for link in soup.find_all("a"):
            href = (link.get("href") or "").strip()
            label = self._compact_text(link.get_text(" ", strip=True))
            absolute_url = urljoin(base_url, href).split("#", 1)[0].rstrip("/")
            if not self._is_allowed_link(absolute_url, base_domain):
                continue
            target_priority = self._target_priority(label, absolute_url, priority_index)
            is_target = target_priority is not None
            if is_target:
                priority = target_priority
            elif self._is_discovery_link(label, absolute_url):
                priority = len(priority_index) + 1
            else:
                continue

            candidate = LinkCandidate(absolute_url, depth, is_target, priority)
            old = candidates.get(absolute_url)
            if not old or (not old.is_target and candidate.is_target) or candidate.priority < old.priority:
                candidates[absolute_url] = candidate

        return sorted(candidates.values(), key=lambda item: (not item.is_target, item.priority, item.depth))

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
    def _target_priority(label: str, url: str, priority_index: dict[str, int]) -> int | None:
        text = f"{label} {url}".lower()
        best: int | None = None
        for module_name, words in TARGET_MODULES.items():
            for word in words:
                if word.lower() in text:
                    priority = priority_index[module_name]
                    if best is None or priority < best:
                        best = priority
        return best

    @staticmethod
    def _is_discovery_link(label: str, url: str) -> bool:
        text = f"{label} {url}".lower()
        return any(word.lower() in text for word in DISCOVERY_WORDS)
