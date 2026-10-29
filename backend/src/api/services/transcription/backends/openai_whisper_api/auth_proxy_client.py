"""Basil Cloud/Auth Service routing for OpenAI transcription."""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

import httpx

from .request_policy import CONNECTION_ERROR_USER_MESSAGE

logger = logging.getLogger(__name__)


class AuthProxyTranscriptionClient:
    """Basil Cloud transcription client for authenticated account routing."""

    def __init__(
        self,
        *,
        api_model_name: Optional[str],
        openrouter_id: Optional[str],
    ) -> None:
        self.api_model_name = api_model_name
        self.openrouter_id = openrouter_id

    async def transcribe_text(
        self,
        wav_bytes: bytes,
        suffix: str,
        language: Optional[str] = None,
        *,
        formatting_prompt: Optional[str] = None,
    ) -> str:
        """Route transcription through the Basil Auth Service to OpenRouter."""
        from api.services.auth_service_client import AUTH_SERVICE_URL
        from api.core.services.model_service import resolve_basil_cloud_credentials

        credentials = await resolve_basil_cloud_credentials("transcription")
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {credentials.access_token}",
        }

        model_for_proxy = self.openrouter_id or self.api_model_name
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        audio_format = suffix.lstrip(".")

        logger.info(
            "Routing transcription through auth proxy (%s): "
            "model=%s, format=%s, %s bytes (%s base64 chars)",
            credentials.label,
            model_for_proxy,
            audio_format,
            len(wav_bytes),
            len(audio_b64),
        )

        payload: Dict[str, Any] = {
            "model": model_for_proxy,
            "audio_base64": audio_b64,
            "audio_format": audio_format,
        }
        if language:
            payload["language"] = language
        if formatting_prompt:
            payload["prompt"] = formatting_prompt

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{AUTH_SERVICE_URL}/route/transcription",
                    json=payload,
                    headers=headers,
                )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.error("Auth-proxy transcription connection failed: %s", exc)
            raise ConnectionError(CONNECTION_ERROR_USER_MESSAGE) from exc

        if response.status_code == 401:
            raise ValueError("Authentication required -- token expired or invalid")
        if response.status_code == 402:
            raise ValueError("Payment required -- please add a payment method")
        if response.status_code == 403:
            raise ValueError("Subscription inactive -- please update your subscription")
        if response.status_code >= 400:
            raise ValueError(
                f"Auth service transcription error ({response.status_code}): {response.text}"
            )

        transcribed_text = response.text.strip()
        logger.info(
            "Auth-proxy transcription complete (%s): %s chars",
            credentials.label,
            len(transcribed_text),
        )
        return transcribed_text
