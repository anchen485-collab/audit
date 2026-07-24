from app.company.cache import CompanyInfoCache
from app.core.models import CompanyInfo


def test_company_cache_treats_empty_file_as_empty_cache(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    cache_path.write_text("", encoding="utf-8")

    cache = CompanyInfoCache(cache_path)

    assert cache.get("不存在的企业") is None


def test_company_cache_treats_invalid_json_as_empty_cache(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    cache_path.write_text("not-json", encoding="utf-8")

    cache = CompanyInfoCache(cache_path)
    info = CompanyInfo(
        query_name="测试企业",
        company_name="测试企业",
        business_scope="蔬菜种植、销售",
        status="",
        source="website",
        success=True,
    )
    cache.set("测试企业", info)

    assert cache.get("测试企业").business_scope == "蔬菜种植、销售"
