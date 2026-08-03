from app.companies.cache import CompanyInfoCache
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


def test_company_cache_merges_latest_file_data_before_write(tmp_path):
    cache_path = tmp_path / "website_cache.json"
    first_cache = CompanyInfoCache(cache_path)
    second_cache = CompanyInfoCache(cache_path)

    first_cache.set(
        "https://first.example",
        CompanyInfo(
            query_name="first",
            company_name="first",
            business_scope="first scope",
            status="",
            source="website",
            success=True,
        ),
    )
    second_cache.set(
        "https://second.example",
        CompanyInfo(
            query_name="second",
            company_name="second",
            business_scope="second scope",
            status="",
            source="website",
            success=True,
        ),
    )

    cache = CompanyInfoCache(cache_path)

    assert cache.get("https://first.example").business_scope == "first scope"
    assert cache.get("https://second.example").business_scope == "second scope"
