from types import SimpleNamespace

import google

from api.core.services.api_key_validation import call_provider_with_key


def test_google_key_validation_disables_automatic_function_calling(monkeypatch):
    captured = {}

    class Models:
        def generate_content(self, *, model, contents, config):
            captured.update(model=model, contents=contents, config=config)

    class Client:
        def __init__(self, *, api_key):
            self.models = Models()
            self.closed = False
            captured["api_key"] = api_key
            captured["client"] = self

        def close(self):
            self.closed = True

    monkeypatch.setattr(google, "genai", SimpleNamespace(Client=Client), raising=False)

    call_provider_with_key("google", "AIza-test", "gemini-test")

    assert captured["model"] == "gemini-test"
    assert captured["contents"] == "Hi"
    assert captured["config"] == {
        "max_output_tokens": 1,
        "automatic_function_calling": {"disable": True},
    }
    assert captured["client"].closed is True
