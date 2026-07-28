from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CleanedWebsiteText:
    text: str
    original_length: int
    cleaned_length: int
    kept_fragment_count: int
    dropped_fragment_count: int
    mode: str = "strict"


class WebsiteTextCleaner:
    """Clean crawled website text into business evidence for downstream classification."""

    CLEANING_VERSION = 6
    BUSINESS_TERMS = (
        "主营",
        "经营",
        "业务",
        "产品",
        "服务",
        "研发",
        "生产",
        "加工",
        "销售",
        "种植",
        "养殖",
        "贸易",
        "供应",
        "解决方案",
        "工程",
        "制造",
        "技术",
        "食品",
        "农业",
        "能源",
        "出口",
        "进口",
        "仓储",
        "供应链",
        "家居",
        "家具",
        "展览",
        "展会",
        "展台",
        "珠宝",
        "饰品",
        "商业空间",
        "动物营养",
        "生物技术",
        "繁育",
    )
    PRIMARY_BUSINESS_TERMS = (
        "主营",
        "经营",
        "业务范围",
        "经营范围",
        "主营业务",
        "种植",
        "养殖",
        "研发",
        "生产",
        "加工",
        "销售",
        "贸易",
        "制造",
        "工程",
        "出口",
        "仓储",
        "供应链",
        "产品系列",
        "解决方案",
        "咨询",
        "设计",
        "搭建",
        "展览",
        "展会",
        "展台",
        "家居",
        "家具",
        "珠宝",
        "动物营养",
        "生物技术",
        "繁育",
    )
    LATIN_BUSINESS_TERMS = (
        "about us",
        "company introduction",
        "business scope",
        "main business",
        "products and services",
        "product",
        "products",
        "service",
        "services",
        "solution",
        "solutions",
        "technology",
        "biotechnology",
        "biotechnologies",
        "research",
        "development",
        "manufacturing",
        "manufacture",
        "production",
        "processing",
        "sales",
        "supply",
        "supplier",
        "export",
        "import",
        "trade",
        "agriculture",
        "livestock",
        "breeding",
        "nutrition",
        "hardware",
        "stainless steel",
        "exhibition",
        "display",
        "design",
        "construction",
        "planning",
    )
    COMPANY_INTRO_HEADINGS = (
        "公司简介",
        "企业简介",
        "关于我们",
        "走进",
        "我们公司",
        "公司概况",
        "公司介绍",
        "企业介绍",
        "品牌介绍",
    )
    BUSINESS_DOMAIN_HEADINGS = (
        "业务范围",
        "业务领域",
        "主营业务",
        "经营范围",
        "服务领域",
    )
    CASE_HEADINGS = (
        "经典案例",
        "客户案例",
        "成功案例",
        "案例展示",
        "项目案例",
    )
    EVIDENCE_HEADINGS = COMPANY_INTRO_HEADINGS + BUSINESS_DOMAIN_HEADINGS + CASE_HEADINGS
    EXCLUDED_SECTION_HEADINGS = (
        "产品服务",
        "产品中心",
        "产品品类",
        "新闻资讯",
        "企业荣誉",
        "荣誉资质",
        "发展历程",
        "联系我们",
        "在线客服",
        "品牌动态",
        "使命",
        "愿景",
        "价值观",
        "总裁致辞",
        "董事长致辞",
        "领导致辞",
        "创始人致辞",
    )
    BOILERPLATE_TERMS = (
        "首页",
        "导航",
        "联系我们",
        "在线留言",
        "加入我们",
        "人才招聘",
        "新闻资讯",
        "版权所有",
        "技术支持",
        "备案号",
        "ICP备",
        "ICP",
        "公网安备",
        "隐私政策",
        "网站地图",
        "返回顶部",
        "扫码关注",
        "微信公众号",
        "友情链接",
        "免责声明",
        "登录",
        "注册",
        "免费量尺",
        "免费设计",
        "快速链接",
        "搜索",
        "PREV",
        "NEXT",
        "All rights reserved",
        "Copyright",
        "Nearby stores",
    )
    PROMOTIONAL_TERMS = (
        "香甜",
        "浓郁",
        "绵密",
        "酸甜",
        "酥脆",
        "软糯",
        "Q弹",
        "上头",
        "口感",
        "滋味",
        "解馋",
        "好气色",
        "代言人",
        "赛事",
        "奖章",
        "荣获",
        "认证",
        "畅销",
        "销量",
        "新闻",
    )
    NOISE_PATTERNS = (
        re.compile(r"[\w.-]+@[\w.-]+"),
        re.compile(r"(?:电话|热线|传真|手机|邮编|邮箱|地址)[:：]?\s*[\w\-+（）() ]{4,}"),
        re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE),
        re.compile(r"\b\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?\b"),
        re.compile(r"\b\d{3,4}[- ]?\d{7,8}\b"),
        re.compile(r"\b(?:copyright|all rights reserved)\b.*", re.IGNORECASE),
    )

    def __init__(self, max_length: int = 6000, min_fragment_length: int = 6):
        self.max_length = max_length
        self.min_fragment_length = min_fragment_length

    def clean(self, text: str) -> CleanedWebsiteText:
        original = text or ""
        normalized = self._normalize(original)
        fragments = self._split_fragments(normalized)
        cleaned = self._clean_strict(original, fragments)
        if cleaned.text or not original.strip():
            return cleaned
        return self._clean_fallback(original, fragments)

    def _clean_strict(self, original: str, fragments: list[str]) -> CleanedWebsiteText:
        kept: list[str] = []
        dropped = 0
        seen: set[str] = set()
        current_section = ""

        for fragment in fragments:
            cleaned = self._clean_fragment(fragment)
            if not cleaned:
                dropped += 1
                continue
            section = self._section_for_fragment(cleaned)
            if section == "excluded":
                current_section = ""
                dropped += 1
                continue
            if section:
                current_section = section
            key = self._dedupe_key(cleaned)
            if key in seen:
                dropped += 1
                continue
            if not self._is_allowed_section_evidence(cleaned, current_section):
                dropped += 1
                continue
            if self._looks_mojibake(cleaned):
                dropped += 1
                continue
            if self._is_noise(cleaned) and not self._has_business_signal(cleaned):
                dropped += 1
                continue
            if self._is_promotional(cleaned) and not self._has_primary_business_signal(cleaned):
                dropped += 1
                continue
            seen.add(key)
            kept.append(cleaned)

        ranked = sorted(kept, key=self._fragment_score, reverse=True)
        cleaned_text = self._limit_text(" ".join(ranked))
        return CleanedWebsiteText(
            text=cleaned_text,
            original_length=len(original),
            cleaned_length=len(cleaned_text),
            kept_fragment_count=len(ranked),
            dropped_fragment_count=dropped,
            mode="strict",
        )

    def _clean_fallback(self, original: str, fragments: list[str]) -> CleanedWebsiteText:
        kept: list[str] = []
        dropped = 0
        seen: set[str] = set()

        for fragment in fragments:
            cleaned = self._clean_fragment(fragment)
            if not cleaned:
                dropped += 1
                continue
            key = self._dedupe_key(cleaned)
            if key in seen:
                dropped += 1
                continue
            if not self._is_fallback_evidence(cleaned):
                dropped += 1
                continue
            seen.add(key)
            kept.append(cleaned)

        ranked = sorted(kept, key=self._fallback_fragment_score, reverse=True)
        cleaned_text = self._limit_text(" ".join(ranked))
        return CleanedWebsiteText(
            text=cleaned_text,
            original_length=len(original),
            cleaned_length=len(cleaned_text),
            kept_fragment_count=len(ranked),
            dropped_fragment_count=dropped,
            mode="fallback",
        )

    def _normalize(self, text: str) -> str:
        text = re.sub(r"[\r\n]+", " | ", text)
        text = re.sub(r"[\u200b\u3000\xa0]+", " ", text)
        for term in self.EVIDENCE_HEADINGS + self.BOILERPLATE_TERMS:
            text = text.replace(term, f" | {term} ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _split_fragments(self, text: str) -> list[str]:
        return [
            item.strip()
            for item in re.split(r"(?<=[。！？；;!?])\s+|\s{2,}|[|｜/]", text)
            if item and item.strip()
        ]

    def _clean_fragment(self, fragment: str) -> str:
        value = fragment.strip(" -_/\\,，.。;；:：")
        for term in self.BOILERPLATE_TERMS:
            value = value.replace(term, " ")
        for pattern in self.NOISE_PATTERNS:
            value = pattern.sub(" ", value)
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) < self.min_fragment_length:
            return ""
        return value

    def _is_noise(self, fragment: str) -> bool:
        if len(fragment) <= 18 and any(term in fragment for term in self.BOILERPLATE_TERMS):
            return True
        boilerplate_hits = sum(1 for term in self.BOILERPLATE_TERMS if term in fragment)
        return boilerplate_hits >= 2

    def _section_for_fragment(self, fragment: str) -> str:
        if any(term in fragment for term in self.EXCLUDED_SECTION_HEADINGS):
            return "excluded"
        if any(term in fragment for term in self.COMPANY_INTRO_HEADINGS):
            return "company_intro"
        if any(term in fragment for term in self.BUSINESS_DOMAIN_HEADINGS):
            return "business_domain"
        if any(term in fragment for term in self.CASE_HEADINGS):
            return "case"
        return ""

    def _is_allowed_section_evidence(self, fragment: str, section: str) -> bool:
        if not section:
            return self._has_primary_business_signal(fragment) or self._has_latin_business_signal(fragment)
        if section in {"company_intro", "business_domain"}:
            return self._has_primary_business_signal(fragment) or self._has_latin_business_signal(fragment)
        if section == "case":
            return self._has_business_signal(fragment) or any(term in fragment for term in self.CASE_HEADINGS)
        return False

    def _has_business_signal(self, fragment: str) -> bool:
        return any(term in fragment for term in self.BUSINESS_TERMS + self.EVIDENCE_HEADINGS) or self._has_latin_business_signal(fragment)

    def _has_primary_business_signal(self, fragment: str) -> bool:
        return any(term in fragment for term in self.PRIMARY_BUSINESS_TERMS)

    def _is_promotional(self, fragment: str) -> bool:
        return any(term in fragment for term in self.PROMOTIONAL_TERMS)

    def _is_fallback_evidence(self, fragment: str) -> bool:
        if self._looks_mojibake(fragment):
            return False
        if self._is_noise(fragment):
            return False
        if self._is_maintenance_text(fragment):
            return False
        if len(fragment) < 12:
            return False
        return self._has_business_signal(fragment) or self._has_latin_business_signal(fragment)

    @staticmethod
    def _looks_mojibake(fragment: str) -> bool:
        mojibake_count = sum(fragment.count(marker) for marker in ["Ã", "Â", "�", "鍔", "绻", "鐧", "棣", "涓"])
        chinese_count = sum(1 for char in fragment if "\u4e00" <= char <= "\u9fff")
        return mojibake_count >= 2 and mojibake_count >= chinese_count * 0.08

    @staticmethod
    def _is_maintenance_text(fragment: str) -> bool:
        return any(term in fragment for term in ["系统更新维护", "正在升级", "敬请期待", "网站建设中"])

    def _has_latin_business_signal(self, fragment: str) -> bool:
        text = fragment.lower()
        return any(term in text for term in self.LATIN_BUSINESS_TERMS)

    def _fragment_score(self, fragment: str) -> tuple[int, int]:
        heading_hits = sum(1 for term in self.EVIDENCE_HEADINGS if term in fragment)
        primary_hits = sum(1 for term in self.PRIMARY_BUSINESS_TERMS if term in fragment)
        business_hits = sum(1 for term in self.BUSINESS_TERMS if term in fragment)
        length_score = min(len(fragment), 300)
        return heading_hits * 5 + primary_hits * 4 + business_hits * 2, length_score

    def _fallback_fragment_score(self, fragment: str) -> tuple[int, int]:
        primary_hits = sum(1 for term in self.PRIMARY_BUSINESS_TERMS if term in fragment)
        business_hits = sum(1 for term in self.BUSINESS_TERMS if term in fragment)
        latin_hits = 1 if self._has_latin_business_signal(fragment) else 0
        length_score = min(len(fragment), 300)
        return primary_hits * 4 + business_hits * 2 + latin_hits * 2, length_score

    def _dedupe_key(self, fragment: str) -> str:
        return re.sub(r"\W+", "", fragment.lower())[:120]

    def _limit_text(self, text: str) -> str:
        if len(text) <= self.max_length:
            return text
        return text[: self.max_length].rsplit(" ", 1)[0].strip() or text[: self.max_length]

