import json
from pathlib import Path

from app.core.models import CompanyInfo


class CompanyInfoCache:
    """简单 JSON 缓存，避免重复查询同一企业。"""

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.cache_path.exists():
            return {}
        return json.loads(self.cache_path.read_text(encoding="utf-8"))

    def get(self, company_name: str) -> CompanyInfo | None:
        item = self._data.get(company_name)
        if not item:
            return None
        return CompanyInfo(**item)

    def set(self, company_name: str, info: CompanyInfo):
        self._data[company_name] = info.__dict__
        self.cache_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
