import hashlib
import os
import time
from typing import Callable

import requests

from app.company.provider import CompanyInfoProvider
from app.core.config import load_env_file
from app.core.models import CompanyInfo


DEFAULT_ENDPOINT = "https://api.qichacha.com/ECIV4/GetBasicDetailsByName"


class QichachaCompanyInfoProvider(CompanyInfoProvider):
    """企查查官方 API Provider，负责请求接口并映射成内部 CompanyInfo。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        endpoint: str | None = None,
        search_param: str | None = None,
        timeout: int | None = None,
        timespan_func: Callable[[], str] | None = None,
        http_get: Callable | None = None,
    ):
        load_env_file()
        self.api_key = api_key if api_key is not None else os.getenv("QICHACHA_API_KEY", "")
        self.api_secret = api_secret if api_secret is not None else os.getenv("QICHACHA_API_SECRET", "")
        self.endpoint = endpoint or os.getenv("QICHACHA_ENDPOINT", DEFAULT_ENDPOINT)
        self.search_param = search_param or os.getenv("QICHACHA_SEARCH_PARAM", "keyword")
        self.timeout = timeout or int(os.getenv("QICHACHA_TIMEOUT", "15"))
        self.timespan_func = timespan_func or (lambda: str(int(time.time())))
        self.http_get = http_get or requests.get

    def get_company_info(self, company_name: str) -> CompanyInfo:
        if not self.api_key or not self.api_secret:
            return self._failed(company_name, "未配置企查查 API Key/Secret")

        try:
            response = self.http_get(
                self.endpoint,
                headers=self._build_headers(),
                params={"key": self.api_key, self.search_param: company_name},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            return self._failed(company_name, f"企查查接口请求失败：{exc}")

        if response.status_code != 200:
            return self._failed(company_name, f"企查查 HTTP 状态异常：{response.status_code}")

        try:
            payload = response.json()
        except ValueError:
            return self._failed(company_name, "企查查响应不是合法 JSON")

        if str(payload.get("Status")) != "200":
            message = payload.get("Message") or payload.get("msg") or response.text
            return self._failed(company_name, f"企查查接口返回失败：{message}", raw=payload)

        result = payload.get("Result") or payload.get("Data") or {}
        if not isinstance(result, dict):
            return self._failed(company_name, "企查查响应 Result 字段格式异常", raw=payload)

        business_scope = self._pick(result, ["Scope", "BusinessScope", "OperScope", "经营范围"])
        mapped_name = self._pick(result, ["Name", "CompanyName", "EntName", "企业名称"]) or company_name
        reg_status = self._pick(result, ["RegStatus", "Status", "StatusDesc", "经营状态"])

        if not business_scope:
            return self._failed(company_name, "企查查响应中未找到经营范围字段", raw=payload)

        return CompanyInfo(
            query_name=company_name,
            company_name=mapped_name,
            business_scope=business_scope,
            status=reg_status,
            source="qichacha",
            success=True,
            raw=payload,
        )

    def _build_headers(self) -> dict[str, str]:
        """按企查查开放平台要求生成 Token 和 Timespan 请求头。"""
        timespan = self.timespan_func()
        token_source = f"{self.api_key}{timespan}{self.api_secret}"
        token = hashlib.md5(token_source.encode("utf-8")).hexdigest().upper()
        return {
            "Token": token,
            "Timespan": timespan,
        }

    def _failed(self, company_name: str, error: str, raw: dict | None = None) -> CompanyInfo:
        """统一构造失败结果，避免上游流程直接崩溃。"""
        return CompanyInfo(
            query_name=company_name,
            company_name=company_name,
            business_scope="",
            status="",
            source="qichacha",
            success=False,
            error=error,
            raw=raw or {},
        )

    @staticmethod
    def _pick(data: dict, keys: list[str]) -> str:
        """从多个可能字段名中取第一个非空值。"""
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
