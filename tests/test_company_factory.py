from app.company.factory import get_company_provider
from app.company.mock_provider import MockCompanyInfoProvider
from app.company.qichacha_provider import QichachaCompanyInfoProvider


def test_get_company_provider_can_switch_to_mock(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "mock")

    provider = get_company_provider()

    assert isinstance(provider, MockCompanyInfoProvider)


def test_get_company_provider_can_switch_to_qichacha(monkeypatch):
    monkeypatch.setenv("COMPANY_PROVIDER", "qichacha")

    provider = get_company_provider()

    assert isinstance(provider, QichachaCompanyInfoProvider)
