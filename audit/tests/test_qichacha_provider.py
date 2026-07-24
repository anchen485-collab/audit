import hashlib

from app.company.qichacha_provider import QichachaCompanyInfoProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_qichacha_provider_maps_success_response(monkeypatch):
    calls = {}

    def fake_get(url, headers, params, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["params"] = params
        calls["timeout"] = timeout
        return FakeResponse(
            {
                "Status": "200",
                "Message": "查询成功",
                "Result": {
                    "Name": "陕西汇生源生态农业有限公司",
                    "Scope": "蔬菜、水果种植、加工、销售。",
                    "RegStatus": "存续",
                },
            }
        )

    provider = QichachaCompanyInfoProvider(
        api_key="test_key",
        api_secret="test_secret",
        timespan_func=lambda: "1700000000",
        http_get=fake_get,
    )

    info = provider.get_company_info("陕西汇生源生态农业有限公司")

    expected_token = hashlib.md5("test_key1700000000test_secret".encode("utf-8")).hexdigest().upper()
    assert info.success is True
    assert info.company_name == "陕西汇生源生态农业有限公司"
    assert info.business_scope == "蔬菜、水果种植、加工、销售。"
    assert info.status == "存续"
    assert calls["headers"]["Token"] == expected_token
    assert calls["headers"]["Timespan"] == "1700000000"
    assert calls["params"]["key"] == "test_key"
    assert calls["params"]["keyword"] == "陕西汇生源生态农业有限公司"


def test_qichacha_provider_returns_api_error_message(monkeypatch):
    def fake_get(url, headers, params, timeout):
        return FakeResponse({"Status": "101", "Message": "余额不足", "Result": None})

    provider = QichachaCompanyInfoProvider(
        api_key="test_key",
        api_secret="test_secret",
        timespan_func=lambda: "1700000000",
        http_get=fake_get,
    )

    info = provider.get_company_info("不存在公司")

    assert info.success is False
    assert info.error == "企查查接口返回失败：余额不足"
