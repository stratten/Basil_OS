"""Reading screenshots of text into plain text, so the person can bring in what another assistant knows about them without copying it out by hand.

The picture is read by the same model route the person confirmed on the setup model step, or the Settings memory model. Only routes that can read pictures are used, and every other route gets a plain explanation instead of a silent failure. The text that comes back goes into the paste box for review, so the rest of the import is unchanged.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Dict, List

ALLOWED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5_000_000
MAX_READ_TOKENS = 4096

READ_INSTRUCTION = (
    "These pictures are screenshots of text a person wants to bring into their assistant, such as a system prompt, custom instructions, or saved memory from another assistant. "
    "Write out all of the text exactly as it appears, in reading order, one picture after another, with no commentary, summary, or added headings. "
    "If a picture has no readable text, write [no readable text] for it."
)


class ImageInputError(ValueError):
    """The pictures themselves cannot be used: too many, too large, or not a picture type that is accepted."""


class ImageRouteError(RuntimeError):
    """The chosen route cannot read pictures. The message says why and what to do instead."""


@dataclass(frozen=True)
class ImportImage:
    mime_type: str
    data_base64: str

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.data_base64}"


def validate_images(raw_images: List[Dict[str, str]]) -> List[ImportImage]:
    """Check the pictures before any model sees them."""
    if not raw_images:
        raise ImageInputError("Choose at least one picture to read.")
    if len(raw_images) > MAX_IMAGES:
        raise ImageInputError(f"Choose at most {MAX_IMAGES} pictures at a time.")
    images: List[ImportImage] = []
    for index, raw in enumerate(raw_images, start=1):
        mime_type = str(raw.get("mime_type", "")).strip().lower()
        if mime_type == "image/jpg":
            mime_type = "image/jpeg"
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise ImageInputError(f"Picture {index} is not a PNG, JPEG, WebP, or GIF image.")
        data = str(raw.get("data_base64", "")).strip()
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageInputError(f"Picture {index} could not be read as an image.") from exc
        if not decoded:
            raise ImageInputError(f"Picture {index} is empty.")
        if len(decoded) > MAX_IMAGE_BYTES:
            raise ImageInputError(f"Picture {index} is larger than {MAX_IMAGE_BYTES // 1_000_000} MB. Crop it or use a smaller screenshot.")
        images.append(ImportImage(mime_type=mime_type, data_base64=data))
    return images


_LOCAL_ROUTE_MESSAGE = (
    "The model you chose runs on this Mac and can only read text, so it cannot read a screenshot. "
    "Paste the text instead, or go back and choose Basil Cloud or a provider key, which can read pictures."
)


def _registry_says_vision(model_name: str) -> bool:
    from api.core.models.models_registry import get_model

    config = get_model(model_name)
    if not config:
        return False
    capabilities = config.get("capabilities", [])
    return "vision" in [getattr(item, "value", item) for item in capabilities]


def _provider_kind(model: Any) -> str:
    """One of claude, openai, gemini, auth_proxy, or other. Compatible endpoints count as other, because they do not promise picture input."""
    from api.core.models.reasoning.auth_proxy_model import AuthProxyModel
    from api.core.models.reasoning.claude_model import ClaudeModel
    from api.core.models.reasoning.gemini_model import GeminiModel
    from api.core.models.reasoning.openai_model import OpenAIModel

    if isinstance(model, AuthProxyModel):
        return "auth_proxy"
    if isinstance(model, ClaudeModel):
        return "claude"
    if isinstance(model, OpenAIModel):
        return "openai"
    if isinstance(model, GeminiModel):
        return "gemini"
    return "other"


def check_route_reads_images(model: Any) -> str:
    """Return the route kind when it can read pictures, or raise ImageRouteError with the reason."""
    kind = _provider_kind(model)
    if kind == "other":
        raise ImageRouteError(_LOCAL_ROUTE_MESSAGE)
    model_name = str(getattr(model, "model_name", "") or "")
    if not _registry_says_vision(model_name):
        label = model_name or "The model you chose"
        raise ImageRouteError(
            f"{label} is not listed as able to read pictures. Paste the text instead, or choose a different model, such as one from Basil Cloud or a provider key that reads pictures."
        )
    return kind


def _text_part(responses_api: bool) -> Dict[str, Any]:
    return {"type": "input_text" if responses_api else "text", "text": READ_INSTRUCTION}


def _image_part(kind: str, image: ImportImage, responses_api: bool) -> Dict[str, Any]:
    if kind == "claude":
        return {"type": "image", "source": {"type": "base64", "media_type": image.mime_type, "data": image.data_base64}}
    if responses_api:
        return {"type": "input_image", "image_url": image.data_url}
    return {"type": "image_url", "image_url": {"url": image.data_url}}


def build_read_message(kind: str, images: List[ImportImage], *, responses_api: bool = False) -> Dict[str, Any]:
    """The single user message that carries the pictures, in the shape the route's provider accepts."""
    parts = [_image_part(kind, image, responses_api) for image in images]
    parts.append(_text_part(responses_api))
    return {"role": "user", "content": parts}


async def read_images_as_text(model: Any, images: List[ImportImage]) -> str:
    """Read the pictures with a route that can, and return the text they contain."""
    kind = check_route_reads_images(model)
    if kind == "gemini":
        text = await model.predict([build_read_message(kind, images)])
    elif kind == "auth_proxy":
        response = await model.chat_completion([build_read_message(kind, images)])
        text = response.get("content", "") if isinstance(response, dict) else response
    else:
        responses_api = kind == "openai" and bool(model._requires_responses_api())
        text = await model.generate_from_messages(
            [build_read_message(kind, images, responses_api=responses_api)],
            max_tokens=MAX_READ_TOKENS,
            enable_web_search=False,
        )
    cleaned = str(text or "").strip()
    if not cleaned or cleaned.replace("[no readable text]", "").strip() == "":
        raise ImageInputError("I could not find any readable text in those pictures. Try a sharper or larger screenshot, or paste the text instead.")
    return cleaned
