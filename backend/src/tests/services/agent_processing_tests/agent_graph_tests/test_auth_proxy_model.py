import importlib

from api.services import auth_service_endpoint
from api.core.models.reasoning.auth_proxy_model import AuthProxyModel


def test_auth_proxy_model_uses_configured_auth_service_url(monkeypatch):
    monkeypatch.setenv("BASIL_AUTH_SERVICE_URL", "https://auth.example.test")

    configured_module = importlib.reload(auth_service_endpoint)

    assert configured_module.AUTH_SERVICE_URL == "https://auth.example.test"

    monkeypatch.delenv("BASIL_AUTH_SERVICE_URL")
    importlib.reload(configured_module)


def test_auth_proxy_model_uses_bearer_header():
    model = AuthProxyModel(
        model_id="claude-sonnet-4-5-20250929",
        access_token="account-token",
    )

    headers = model._build_headers()

    assert headers["Authorization"] == "Bearer account-token"
    assert "X-Trial-Key" not in headers
    assert "X-Basil-Setup-Agent-Key" not in headers
