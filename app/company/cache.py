import json
import logging
from pathlib import Path

from app.core.models import CompanyInfo


logger = logging.getLogger(__name__)


class CompanyInfoCache:
    """简单 JSON 缓存，避免重复查询同一企业。"""

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.cache_path.exists():
            return {}
        raw_text = self.cache_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            logger.warning("company_cache_empty 缓存文件为空，将按空缓存处理 cache_path=%s", self.cache_path)
            return {}
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "company_cache_invalid 缓存文件不是合法 JSON，将按空缓存处理 cache_path=%s error=%s",
                self.cache_path,
                exc,
            )
            return {}
        if not isinstance(data, dict):
            logger.warning("company_cache_invalid_type 缓存内容不是对象，将按空缓存处理 cache_path=%s", self.cache_path)
            return {}
        return data

    def get(self, company_name: str) -> CompanyInfo | None:
        item = self._data.get(company_name)
        if not item:
            return None
        return CompanyInfo(**item)

    def set(self, company_name: str, info: CompanyInfo):
        self._data[company_name] = info.__dict__
        self.cache_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
