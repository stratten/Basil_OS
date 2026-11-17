"""Reading screenshots into text: picture validation, which routes can read pictures, the message each provider receives, and the HTTP mapping."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.models.reasoning.auth_proxy_model import AuthProxyModel
from api.core.models.reasoning.claude_model import ClaudeModel
from api.core.models.reasoning.gemini_model import GeminiModel
from api.core.models.reasoning.openai_model import OpenAIModel
from api.routes.memory import context_import_routes
from api.routes.memory.context_import_routes import router
from api.services.memory.context_import import image_reading
from api.services.memory.context_import.image_reading import (
    ImageInputError,
    ImageRouteError,
    ImportImage,
    build_read_message,
    check_route_reads_images,
    read_images_as_text,
    validate_images,
)

PNG_BASE64 = base64.b64encode(b"\x89PNG fake picture bytes").decode()


def _raw(mime="image/png", data=PNG_BASE64):
    return {"mime_type": mime, "data_base64": data}


def _image():
    return ImportImage(mime_type="image/png", data_base64=PNG_BASE64)


def _fake(cls, model_name="vision-model", **methods):
    instance = object.__new__(cls)
    instance.model_name = model_name
    for name, function in methods.items():
        setattr(instance, name, function)
    return instance


@pytest.fixture(autouse=True)
def _vision_registry(monkeypatch):
    monkeypatch.setattr(image_reading, "_registry_says_vision", lambda name: name.startswith("vision"))


def test_validate_images_accepts_pictures_and_normalizes_jpg():
    images = validate_images([_raw(), _raw("image/JPG")])

    assert [image.mime_type for image in images] == ["image/png", "image/jpeg"]
    assert images[0].data_url == f"data:image/png;base64,{PNG_BASE64}"


@pytest.mark.parametrize(
    "raw_images, fragment",
    [
        ([], "at least one"),
        ([_raw()] * 7, "at most 6"),
        ([_raw("application/pdf")], "not a PNG"),
        ([_raw(data="not base64!!")], "could not be read"),
        ([_raw(data="")], "is empty"),
    ],
)
def test_validate_images_rejects_unusable_input(raw_images, fragment):
    with pytest.raises(ImageInputError, match=fragment):
        validate_images(raw_images)


def test_validate_images_rejects_an_oversized_picture(monkeypatch):
    monkeypatch.setattr(image_reading, "MAX_IMAGE_BYTES", 4)

    with pytest.raises(ImageInputError, match="larger than"):
        validate_images([_raw()])


def test_a_local_model_gets_a_plain_explanation_and_a_way_forward():
    with pytest.raises(ImageRouteError) as raised:
        check_route_reads_images(object())

    assert "runs on this Mac" in str(raised.value)
    assert "Paste the text instead" in str(raised.value)


def test_a_cloud_model_without_vision_is_refused_by_name():
    with pytest.raises(ImageRouteError, match="text-only-model is not listed as able to read pictures"):
        check_route_reads_images(_fake(OpenAIModel, "text-only-model"))


@pytest.mark.parametrize(
    "cls, kind",
    [(ClaudeModel, "claude"), (OpenAIModel, "openai"), (GeminiModel, "gemini"), (AuthProxyModel, "auth_proxy")],
)
def test_vision_capable_routes_are_accepted(cls, kind):
    assert check_route_reads_images(_fake(cls)) == kind


def test_each_provider_gets_the_picture_in_its_own_shape():
    claude = build_read_message("claude", [_image()])["content"]
    chat = build_read_message("openai", [_image()])["content"]
    responses = build_read_message("openai", [_image()], responses_api=True)["content"]

    assert claude[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_BASE64}}
    assert chat[0] == {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_BASE64}"}}
    assert responses[0] == {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_BASE64}"}
    assert [claude[-1]["type"], chat[-1]["type"], responses[-1]["type"]] == ["text", "text", "input_text"]


@pytest.mark.anyio
async def test_claude_reads_through_generate_from_messages_without_web_search():
    seen = {}

    async def generate_from_messages(messages, *, max_tokens, enable_web_search):
        seen.update(messages=messages, max_tokens=max_tokens, enable_web_search=enable_web_search)
        return "  Always answer briefly.  "

    text = await read_images_as_text(_fake(ClaudeModel, generate_from_messages=generate_from_messages), [_image()])

    assert text == "Always answer briefly."
    assert seen["enable_web_search"] is False
    assert seen["messages"][0]["content"][0]["type"] == "image"


@pytest.mark.anyio
async def test_openai_responses_models_receive_input_image_parts():
    seen = {}

    async def generate_from_messages(messages, *, max_tokens, enable_web_search):
        seen["messages"] = messages
        return "text"

    model = _fake(OpenAIModel, generate_from_messages=generate_from_messages, _requires_responses_api=lambda: True)
    await read_images_as_text(model, [_image()])

    assert seen["messages"][0]["content"][0]["type"] == "input_image"


@pytest.mark.anyio
async def test_gemini_reads_through_predict_and_the_auth_proxy_through_chat_completion():
    async def predict(messages):
        return "from gemini"

    async def chat_completion(messages):
        return {"content": "from the proxy"}

    assert await read_images_as_text(_fake(GeminiModel, predict=predict), [_image()]) == "from gemini"
    assert await read_images_as_text(_fake(AuthProxyModel, chat_completion=chat_completion), [_image()]) == "from the proxy"


@pytest.mark.anyio
@pytest.mark.parametrize("answer", ["", "   ", "[no readable text]"])
async def test_an_answer_with_no_text_is_reported_instead_of_returned(answer):
    async def generate_from_messages(messages, *, max_tokens, enable_web_search):
        return answer

    with pytest.raises(ImageInputError, match="could not find any readable text"):
        await read_images_as_text(_fake(ClaudeModel, generate_from_messages=generate_from_messages), [_image()])


class _Loaded:
    def __init__(self, model):
        self.model = model


def _client(monkeypatch, model=None, error=None):
    async def load_settings_model():
        if error is not None:
            raise error
        return _Loaded(model)

    monkeypatch.setattr(context_import_routes, "load_settings_import_model", load_settings_model)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_the_route_returns_the_text_the_model_read(monkeypatch):
    async def generate_from_messages(messages, *, max_tokens, enable_web_search):
        return "Prefers short answers."

    client = _client(monkeypatch, _fake(ClaudeModel, generate_from_messages=generate_from_messages))

    response = client.post("/memory/context-import/images/read", json={"images": [_raw()]})

    assert response.status_code == 200
    assert response.json() == {"text": "Prefers short answers."}


def test_the_route_maps_a_text_only_route_to_400_with_the_explanation(monkeypatch):
    client = _client(monkeypatch, object())

    response = client.post("/memory/context-import/images/read", json={"images": [_raw()]})

    assert response.status_code == 400
    assert "runs on this Mac" in response.json()["detail"]


def test_the_route_maps_bad_pictures_to_422_and_model_failures_to_502(monkeypatch):
    client = _client(monkeypatch, object())
    bad = client.post("/memory/context-import/images/read", json={"images": [_raw("text/plain")]})

    async def generate_from_messages(messages, *, max_tokens, enable_web_search):
        raise RuntimeError("provider down")

    failing = _client(monkeypatch, _fake(ClaudeModel, generate_from_messages=generate_from_messages))
    failed = failing.post("/memory/context-import/images/read", json={"images": [_raw()]})

    assert bad.status_code == 422
    assert failed.status_code == 502
    assert "paste the text instead" in failed.json()["detail"]
