from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import logging
import re
import threading
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests


logger = logging.getLogger(__name__)


TARGET_MODULES = {
    "业务领域": ["业务领域", "业务范围", "主营业务", "产品服务", "产品中心", "服务领域"],
    "公司简介": [
        "公司简介",
        "企业简介",
        "关于我们",
        "公司介绍",
        "企业介绍",
        "公司概况",
        "企业概况",
        "品牌介绍",
        "走进我们",
        "走进企业",
        "关于",
    ],
    "经典案例": ["经典案例", "客户案例", "成功案例", "案例展示", "项目案例"],
}
DISCOVERY_WORDS = [
    "了解更多",
    "更多",
    "关于",
    "简介",
    "介绍",
    "概况",
    "走进",
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
DEFAULT_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


class WebsiteFetchStatusError(requests.RequestException):
    """页面返回非成功 HTTP 状态码。"""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


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
                fallback_url = self._fallback_start_url(current.url, exc)
                if not visited and fallback_url and fallback_url not in queued and fallback_url not in fetched_html:
                    logger.info(
                        "website_crawl_retry_site_root 首页路径访问失败，尝试官网根地址 url=%s fallback_url=%s error=%s",
                        current.url,
                        fallback_url,
                        exc,
                    )
                    queued.add(fallback_url)
                    queue.appendleft(LinkCandidate(fallback_url, 0, True, 0))
                    continue
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
            # 链接文字可能很泛，例如“了解更多”；抓到页面后再用标题、面包屑、正文做一次目标页判断。
            if current.is_target or self._is_target_page(current.url, html):
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
            if self._is_footer_link(link):
                continue
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
        response = self._http_get(url)
        if response.status_code == 403 and url.startswith("http://"):
            secure_url = "https://" + url[len("http://") :]
            logger.info("website_crawl_retry_https HTTP 403 后尝试 HTTPS url=%s secure_url=%s", url, secure_url)
            secure_response = self._http_get(secure_url)
            if secure_response.status_code < 400:
                response = secure_response
        if response.status_code >= 400:
            raise WebsiteFetchStatusError(response.status_code)
        return self._decode_response_text(response)

    def _http_get(self, url: str):
        return self.http_get(
            url,
            timeout=self.timeout,
            headers=self._request_headers(url),
        )

    @staticmethod
    def _request_headers(url: str) -> dict[str, str]:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
        headers = dict(DEFAULT_REQUEST_HEADERS)
        if base_url:
            headers["Referer"] = base_url
        return headers

    @staticmethod
    def _fallback_start_url(url: str, exc: Exception) -> str:
        if not isinstance(exc, WebsiteFetchStatusError) or exc.status_code != 404:
            return ""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        if parsed.path in {"", "/"} and not parsed.query:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _decode_response_text(response) -> str:
        """根据响应字节选择更可靠的编码，减少官网中文乱码。"""
        content = getattr(response, "content", None)
        if isinstance(content, bytes | bytearray):
            best_text = ""
            best_score = -10**9
            for encoding in WebsiteCrawler._candidate_encodings(response):
                try:
                    text = bytes(content).decode(encoding, errors="replace")
                except LookupError:
                    continue
                score = WebsiteCrawler._text_quality_score(text)
                if score > 0 and not WebsiteCrawler._looks_mojibake(text):
                    return text
                if score > best_score:
                    best_text = text
                    best_score = score
            if best_text:
                return best_text

        text = response.text
        repaired_text = WebsiteCrawler._repair_mojibake(text)
        return repaired_text or text

    @staticmethod
    def _candidate_encodings(response) -> list[str]:
        """按可信度排列候选编码，优先使用 requests 探测到的 apparent_encoding。"""
        candidates = [
            getattr(response, "apparent_encoding", None),
            getattr(response, "encoding", None),
            "utf-8",
            "gb18030",
            "gbk",
        ]
        result: list[str] = []
        for encoding in candidates:
            if not encoding:
                continue
            encoding = str(encoding).strip()
            if encoding and encoding.lower() not in {item.lower() for item in result}:
                result.append(encoding)
        return result

    @staticmethod
    def _text_quality_score(text: str) -> int:
        """给解码结果打分：中文越多越好，乱码特征越多越差。"""
        chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        mojibake_count = sum(text.count(marker) for marker in ["Ã", "Â", "�", "é", "å", "ç", "è", "\\x"])
        return chinese_count * 2 - mojibake_count * 5

    @staticmethod
    def _repair_mojibake(text: str) -> str:
        """兜底修复已经被 Latin-1 解错的 UTF-8 文本。"""
        if not WebsiteCrawler._looks_mojibake(text):
            return ""
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except UnicodeError:
            return ""
        if WebsiteCrawler._text_quality_score(repaired) > WebsiteCrawler._text_quality_score(text):
            return repaired
        return ""

    @staticmethod
    def _looks_mojibake(text: str) -> bool:
        """判断文本是否存在常见的中文乱码特征。"""
        return any(marker in text for marker in ["Ã", "Â", "�", "é", "å", "ç", "è", "\\x"])

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

    @staticmethod
    def _is_target_page(url: str, html: str) -> bool:
        """用页面标题、面包屑和正文片段补判目标页，覆盖“了解更多 -> 关于品牌”这类结构。"""
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        headings = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2", "h3"]))
        body_preview = WebsiteCrawler._compact_text(soup.get_text(" ", strip=True))[:800]
        priority_index = {name: index for index, name in enumerate(TARGET_MODULES)}
        return WebsiteCrawler._target_priority(f"{title} {headings} {body_preview}", url, priority_index) is not None

    @staticmethod
    def _is_footer_link(link) -> bool:
        """跳过页面底部的导航和资源链接，避免把地址、门店、素材中心等低价值页面加入爬取队列。"""
        for parent in [link, *link.parents]:
            tag_name = getattr(parent, "name", "") or ""
            if tag_name.lower() == "footer":
                return True
            attrs_text = WebsiteCrawler._node_attrs_text(parent)
            if any(marker in attrs_text for marker in ["footer", "foot", "copyright", "底部", "页脚"]):
                return True
        return False

    @staticmethod
    def _node_attrs_text(node) -> str:
        class_value = node.get("class") or []
        if isinstance(class_value, str):
            class_text = class_value
        else:
            class_text = " ".join(str(item) for item in class_value)
        values = [
            node.get("id") or "",
            class_text,
            node.get("role") or "",
            node.get("aria-label") or "",
        ]
        return " ".join(str(value) for value in values).lower()


class Crawl4AIWebsiteCrawler:
    """使用 Crawl4AI 作为浏览器级官网爬取适配器。"""

    def __init__(
        self,
        max_pages: int = 4,
        max_depth: int = 2,
        timeout: int = 8,
        min_text_length: int = 20,
        max_text_length: int = 12000,
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.timeout = timeout
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length

    def crawl(self, url: str) -> WebsiteCrawlResult:
        """通过 Crawl4AI 抓取动态官网内容，并返回项目内统一结果对象。"""
        normalized_url = WebsiteCrawler._normalize_start_url(url)
        if not normalized_url:
            logger.warning("crawl4ai_crawl_invalid_url 官网链接格式异常 url=%s", url)
            return WebsiteCrawlResult(success=False, url=url, error="官网链接格式异常")

        logger.info(
            "crawl4ai_crawl_start Crawl4AI 官网爬取开始 url=%s max_pages=%s max_depth=%s timeout=%s",
            normalized_url,
            self.max_pages,
            self.max_depth,
            self.timeout,
        )
        try:
            return self._run_async(lambda: self._crawl_async(normalized_url))
        except ImportError as exc:
            logger.warning("crawl4ai_crawl_missing_dependency Crawl4AI 未安装 url=%s error=%s", normalized_url, exc)
            return WebsiteCrawlResult(success=False, url=normalized_url, error="Crawl4AI 未安装或未完成浏览器初始化")
        except Exception as exc:
            logger.warning("crawl4ai_crawl_failed Crawl4AI 官网爬取失败 url=%s error=%s", normalized_url, exc)
            return WebsiteCrawlResult(success=False, url=normalized_url, error=f"Crawl4AI 官网爬取失败：{exc}")

    async def _crawl_async(self, normalized_url: str) -> WebsiteCrawlResult:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

        browser_config = BrowserConfig(headless=True)
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            deep_crawl_strategy=BFSDeepCrawlStrategy(
                max_depth=self.max_depth,
                include_external=False,
                max_pages=self.max_pages,
            ),
            exclude_external_links=True,
            remove_overlay_elements=True,
            process_iframes=True,
            page_timeout=self.timeout * 1000,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            raw_results = await crawler.arun(url=normalized_url, config=run_config)

        results = raw_results if isinstance(raw_results, list) else [raw_results]
        visited_urls: list[str] = []
        evidence_texts: list[str] = []

        for index, result in enumerate(results[: self.max_pages]):
            result_url = getattr(result, "url", normalized_url)
            if result_url:
                visited_urls.append(result_url)
            if not getattr(result, "success", False):
                continue

            text = self._result_text(result)
            if not text:
                continue
            if index == 0 or self._is_target_result(result_url, text):
                evidence_texts.append(text)

        if not evidence_texts:
            evidence_texts = [self._result_text(result) for result in results[: self.max_pages] if getattr(result, "success", False)]

        text = WebsiteCrawler._compact_text(" ".join(evidence_texts))[: self.max_text_length]
        if len(text) < self.min_text_length:
            error = self._first_error(results) or "官网证据不足"
            logger.warning(
                "crawl4ai_crawl_insufficient_evidence Crawl4AI 官网证据不足 url=%s visited_count=%s text_length=%s error=%s",
                normalized_url,
                len(visited_urls),
                len(text),
                error,
            )
            return WebsiteCrawlResult(success=False, url=normalized_url, text=text, visited_urls=visited_urls, error=error)

        logger.info(
            "crawl4ai_crawl_success Crawl4AI 官网爬取成功 url=%s visited_count=%s text_length=%s",
            normalized_url,
            len(visited_urls),
            len(text),
        )
        return WebsiteCrawlResult(success=True, url=normalized_url, text=text, visited_urls=visited_urls)

    @staticmethod
    def _run_async(coro_factory):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro_factory())

        result = {}

        def runner():
            try:
                result["value"] = asyncio.run(coro_factory())
            except Exception as exc:  # pragma: no cover - re-raised in caller thread
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in result:
            raise result["error"]
        return result["value"]

    @staticmethod
    def _result_text(result) -> str:
        markdown = getattr(result, "markdown", "")
        if hasattr(markdown, "fit_markdown") and markdown.fit_markdown:
            return WebsiteCrawler._compact_text(markdown.fit_markdown)
        if hasattr(markdown, "raw_markdown") and markdown.raw_markdown:
            return WebsiteCrawler._compact_text(markdown.raw_markdown)
        if isinstance(markdown, str) and markdown:
            return WebsiteCrawler._compact_text(markdown)
        cleaned_html = getattr(result, "cleaned_html", "") or getattr(result, "html", "")
        if cleaned_html:
            return WebsiteCrawler().extract_text(cleaned_html)
        return ""

    @staticmethod
    def _is_target_result(url: str, text: str) -> bool:
        priority_index = {name: index for index, name in enumerate(TARGET_MODULES)}
        return WebsiteCrawler._target_priority(text[:500], url, priority_index) is not None

    @staticmethod
    def _first_error(results) -> str:
        for result in results:
            error = getattr(result, "error_message", "") or getattr(result, "error", "")
            if error:
                return str(error)
        return ""


class HybridWebsiteCrawler:
    """先使用轻量爬虫，失败时自动兜底到 Crawl4AI。"""

    def __init__(self, primary: WebsiteCrawler, fallback: Crawl4AIWebsiteCrawler):
        self.primary = primary
        self.fallback = fallback
        self.max_pages = primary.max_pages
        self.max_depth = primary.max_depth
        self.timeout = primary.timeout
        self.min_text_length = primary.min_text_length
        self.max_text_length = primary.max_text_length

    def crawl(self, url: str) -> WebsiteCrawlResult:
        primary_result = self.primary.crawl(url)
        if primary_result.success or not self._should_fallback(primary_result):
            return primary_result

        logger.info(
            "website_crawl_fallback_to_crawl4ai 轻量爬虫失败，切换 Crawl4AI url=%s error=%s",
            primary_result.url,
            primary_result.error,
        )
        fallback_result = self.fallback.crawl(url)
        if fallback_result.success:
            fallback_result.visited_urls = self._merge_urls(primary_result.visited_urls, fallback_result.visited_urls)
            return fallback_result

        return WebsiteCrawlResult(
            success=False,
            url=fallback_result.url or primary_result.url,
            text=fallback_result.text or primary_result.text,
            visited_urls=self._merge_urls(primary_result.visited_urls, fallback_result.visited_urls),
            error=f"{primary_result.error}；Crawl4AI 兜底失败：{fallback_result.error}",
        )

    @staticmethod
    def _should_fallback(result: WebsiteCrawlResult) -> bool:
        return result.error != "官网链接格式异常"

    @staticmethod
    def _merge_urls(first: list[str], second: list[str]) -> list[str]:
        merged: list[str] = []
        for url in [*first, *second]:
            if url and url not in merged:
                merged.append(url)
        return merged
