import importlib

from api.services import auth_service_endpoint
from api.core.models.reasoning.auth_proxy_model import AuthProxyModel


def test_auth_proxy_model_uses_configured_auth_service_url(monkeypatch):
    monkeypatch.setenv("BASIL_AUTH_SERVICE_URL", "https://auth.example.test")

    configured_module = importlib.reload(auth_service_endpoint)

    assert configured_module.AUTH_SERVICE_URL == "https://auth.example.test"

    monkeypatch.delenv("BASIL_AUTH_SERVICE_URL")
    importlib.reload(configured_module)


def test_auth_proxy_model_uses_setup_agent_header_without_trial_or_bearer_headers():
    model = AuthProxyModel(
        model_id="claude-sonnet-4-5-20250929",
        setup_agent_key="setup-agent-secret",
    )

    headers = model._build_headers()

    assert headers["X-Basil-Setup-Agent-Key"] == "setup-agent-secret"
    assert "X-Trial-Key" not in headers
    assert "Authorization" not in headers
    assert model._current_auth_label() == "setup_agent"
