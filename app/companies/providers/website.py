import logging
from pathlib import Path
from time import perf_counter

from app.preprocessing import WebsiteTextCleaner
from app.companies.cache import CompanyInfoCache
from app.companies.providers.base import CompanyInfoProvider
from app.companies.text_repair import looks_mojibake, repair_compacted_text
from app.companies.crawlers.website import WebsiteCrawler
from app.core.models import CompanyInfo, EmployeeRecord
from app.core.trace import elapsed_ms


logger = logging.getLogger(__name__)


class WebsiteCompanyInfoProvider(CompanyInfoProvider):
    """从企业官网定向抓取外部证据文本。"""

    def __init__(
        self,
        crawler: WebsiteCrawler | None = None,
        cache_path: str | Path | None = None,
        text_cleaner: WebsiteTextCleaner | None = None,
    ):
        self.crawler = crawler or WebsiteCrawler()
        self.cache = CompanyInfoCache(cache_path) if cache_path else None
        self.text_cleaner = text_cleaner or WebsiteTextCleaner()

    def get_company_info(self, company_name: str) -> CompanyInfo:
        return CompanyInfo(
            query_name=company_name,
            company_name=company_name,
            business_scope="",
            status="",
            source="website",
            success=False,
            error="官网模式需要企业官网链接",
        )

    def get_company_info_for_record(self, record: EmployeeRecord) -> CompanyInfo:
        provider_start = perf_counter()
        if not record.website_url:
            logger.warning("website_provider_missing_url 官网链接缺失 company=%s row=%s", record.company_raw, record.row_number)
            logger.info(
                "website_provider_timing 官网信息源耗时 company=%s cache_hit=false success=false duration_ms=%.2f",
                record.company_raw,
                elapsed_ms(provider_start),
            )
            return self._failed(record, "官网链接缺失")

        if self.cache:
            cached = self.cache.get(record.website_url)
            if cached:
                if cached.success:
                    cache_duration_ms = elapsed_ms(provider_start)
                    logger.info(
                        "website_provider_cache_hit 官网成功缓存命中 company=%s url=%s duration_ms=%.2f",
                        record.company_raw,
                        record.website_url,
                        cache_duration_ms,
                    )
                    cached = self._upgrade_cached_info(record, cached)
                    if cached.business_scope:
                        self.cache.set(record.website_url, cached)
                        logger.info(
                            "website_provider_timing 官网信息源耗时 company=%s cache_hit=true success=true duration_ms=%.2f",
                            record.company_raw,
                            elapsed_ms(provider_start),
                        )
                        return cached
                    logger.info(
                        "website_provider_empty_success_cache_ignored 官网成功缓存缺少有效业务文本，将重新爬取 company=%s url=%s",
                        record.company_raw,
                        record.website_url,
                    )
                else:
                    logger.info(
                        "website_provider_failed_cache_ignored 官网失败缓存已忽略，将重新爬取 company=%s url=%s error=%s",
                        record.company_raw,
                        record.website_url,
                        cached.error,
                    )

        logger.info("website_provider_crawl_start 开始从官网获取企业信息 company=%s url=%s", record.company_raw, record.website_url)
        crawl_start = perf_counter()
        crawl_result = self.crawler.crawl(record.website_url)
        crawl_duration_ms = elapsed_ms(crawl_start)
        if not crawl_result.success:
            logger.warning(
                "website_provider_crawl_failed 官网企业信息获取失败 company=%s url=%s error=%s visited_count=%s duration_ms=%.2f",
                record.company_raw,
                record.website_url,
                crawl_result.error,
                len(crawl_result.visited_urls),
                crawl_duration_ms,
            )
            info = self._failed(record, crawl_result.error, crawl_result)
            if self.cache:
                self.cache.set(record.website_url, info)
            logger.info(
                "website_provider_timing 官网信息源耗时 company=%s cache_hit=false success=false duration_ms=%.2f",
                record.company_raw,
                elapsed_ms(provider_start),
            )
            return info

        logger.info(
            "website_provider_crawl_success 官网企业信息获取成功 company=%s url=%s visited_count=%s text_length=%s duration_ms=%.2f",
            record.company_raw,
            record.website_url,
            len(crawl_result.visited_urls),
            len(crawl_result.text or ""),
            crawl_duration_ms,
        )
        clean_start = perf_counter()
        source_text = repair_compacted_text(crawl_result.text)
        cleaned = self.text_cleaner.clean(source_text)
        clean_duration_ms = elapsed_ms(clean_start)
        business_scope, fallback_to_raw_text = self._business_scope_from_cleaned(cleaned.text, source_text)
        logger.info(
            "website_provider_text_cleaned 官网文本清洗完成 company=%s original_length=%s cleaned_length=%s kept_fragments=%s dropped_fragments=%s duration_ms=%.2f",
            record.company_raw,
            cleaned.original_length,
            cleaned.cleaned_length,
            cleaned.kept_fragment_count,
            cleaned.dropped_fragment_count,
            clean_duration_ms,
        )
        if not business_scope:
            logger.warning(
                "website_provider_text_empty 官网文本清洗后无有效业务证据 company=%s url=%s raw_length=%s",
                record.company_raw,
                record.website_url,
                len(crawl_result.text or ""),
            )
            info = self._failed(record, "官网文本清洗后无有效业务证据", crawl_result)
            info.raw["raw_crawl_text"] = source_text
            info.raw["cleaning"] = self._cleaning_payload(cleaned, fallback_to_raw_text=fallback_to_raw_text)
            if self.cache:
                self.cache.set(record.website_url, info)
            return info
        info = CompanyInfo(
            query_name=record.company_name or record.company_raw,
            company_name=record.company_name or record.company_raw,
            business_scope=business_scope,
            status="",
            source="website",
            success=True,
            raw={
                "website_url": record.website_url,
                "visited_urls": crawl_result.visited_urls,
                "raw_crawl_text": source_text,
                "cleaning": self._cleaning_payload(cleaned, fallback_to_raw_text=fallback_to_raw_text),
            },
        )
        if self.cache:
            self.cache.set(record.website_url, info)
        logger.info(
            "website_provider_timing 官网信息源耗时 company=%s cache_hit=false success=true duration_ms=%.2f",
            record.company_raw,
            elapsed_ms(provider_start),
        )
        return info

    def _failed(self, record: EmployeeRecord, error: str, crawl_result=None) -> CompanyInfo:
        return CompanyInfo(
            query_name=record.company_name or record.company_raw,
            company_name=record.company_name or record.company_raw,
            business_scope=getattr(crawl_result, "text", ""),
            status="",
            source="website",
            success=False,
            error=error,
            raw={
                "website_url": record.website_url,
                "visited_urls": getattr(crawl_result, "visited_urls", []),
            },
        )

    def _upgrade_cached_info(self, record: EmployeeRecord, info: CompanyInfo) -> CompanyInfo:
        cleaning = info.raw.get("cleaning", {})
        source_text = info.raw.get("raw_crawl_text") or info.business_scope
        repaired_source_text = repair_compacted_text(source_text)
        cached_text_has_mojibake = looks_mojibake(info.business_scope) or looks_mojibake(source_text)
        if cleaning.get("version") == self.text_cleaner.CLEANING_VERSION and not cached_text_has_mojibake and info.business_scope:
            return info

        cleaned = self.text_cleaner.clean(repaired_source_text)
        business_scope, fallback_to_raw_text = self._business_scope_from_cleaned(cleaned.text, repaired_source_text)
        logger.info(
            "website_provider_cache_cleaned 官网旧缓存已重新清洗 company=%s original_length=%s cleaned_length=%s",
            record.company_raw,
            cleaned.original_length,
            cleaned.cleaned_length,
        )
        raw = dict(info.raw)
        raw["raw_crawl_text"] = repaired_source_text
        raw["cleaning"] = self._cleaning_payload(cleaned, fallback_to_raw_text=fallback_to_raw_text)
        return CompanyInfo(
            query_name=info.query_name,
            company_name=info.company_name,
            business_scope=business_scope,
            status=info.status,
            source=info.source,
            success=info.success,
            error=info.error,
            raw=raw,
        )

    def _business_scope_from_cleaned(self, cleaned_text: str, source_text: str) -> tuple[str, bool]:
        """清洗器无法识别英文证据时，保留原文，避免后续 Agent 没有证据可判断。"""
        if cleaned_text:
            return cleaned_text, False
        fallback = repair_compacted_text(source_text)
        if self.text_cleaner._is_maintenance_text(fallback):
            return "", False
        return fallback, bool(fallback)

    def _cleaning_payload(self, cleaned, fallback_to_raw_text: bool = False) -> dict:
        return {
            "version": self.text_cleaner.CLEANING_VERSION,
            "original_length": cleaned.original_length,
            "cleaned_length": cleaned.cleaned_length,
            "kept_fragment_count": cleaned.kept_fragment_count,
            "dropped_fragment_count": cleaned.dropped_fragment_count,
            "mode": cleaned.mode,
            "fallback_to_raw_text": fallback_to_raw_text,
        }

