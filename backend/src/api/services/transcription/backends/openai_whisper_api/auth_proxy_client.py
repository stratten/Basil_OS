"""Basil Cloud/Auth Service routing for OpenAI transcription."""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

import httpx

from .request_policy import CONNECTION_ERROR_USER_MESSAGE

logger = logging.getLogger(__name__)


async def broadcast_trial_balance_from_headers(
    response: httpx.Response,
    force_exhausted: bool = False,
) -> None:
    """Broadcast auth-service trial balance metadata using the shared event shape."""
    remaining_usd_header = response.headers.get("X-Trial-Remaining-Usd")
    remaining_cents_header = response.headers.get("X-Trial-Remaining-Cents")
    limit_usd_header = response.headers.get("X-Trial-Limit-Usd")

    try:
        remaining_usd: float | None = 0.0 if force_exhausted else None
        if remaining_usd_header is not None:
            remaining_usd = float(remaining_usd_header)
        elif remaining_cents_header is not None:
            remaining_usd = int(remaining_cents_header) / 100.0

        if remaining_usd is None:
            return

        message: Dict[str, Any] = {
            "event_type": "trial_balance_update",
            "remaining_usd": remaining_usd,
            "is_exhausted": remaining_usd <= 0.000001,
        }
        if limit_usd_header is not None:
            message["limit_usd"] = float(limit_usd_header)

        from api.services.websocket_connection_manager import active_connections
        for ws in active_connections:
            await ws.send_json(message)
    except Exception as exc:
        logger.warning("Failed to broadcast trial balance: %s", exc)


class AuthProxyTranscriptionClient:
    """Basil Cloud transcription client for APP_KEYS and TRIAL routing."""

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

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        credentials = await resolve_basil_cloud_credentials("transcription")

        if credentials.trial_key:
            headers["X-Trial-Key"] = credentials.trial_key
            auth_label = "basil_cloud_trial_first"
        else:
            headers["Authorization"] = f"Bearer {credentials.access_token}"
            auth_label = "basil_cloud_account"

        model_for_proxy = self.openrouter_id or self.api_model_name
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        audio_format = suffix.lstrip(".")

        logger.info(
            "Routing transcription through auth proxy (%s): "
            "model=%s, format=%s, %s bytes (%s base64 chars)",
            auth_label,
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
                if (
                    response.status_code == 402
                    and "trial" in response.text.lower()
                    and credentials.access_token
                ):
                    await broadcast_trial_balance_from_headers(response, force_exhausted=True)
                    logger.info("Trial exhausted; retrying transcription with Basil account token")
                    response = await client.post(
                        f"{AUTH_SERVICE_URL}/route/transcription",
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {credentials.access_token}",
                        },
                    )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.error("Auth-proxy transcription connection failed: %s", exc)
            raise ConnectionError(CONNECTION_ERROR_USER_MESSAGE) from exc

        if response.status_code == 401:
            raise ValueError("Authentication required -- token expired or invalid")
        if response.status_code == 402:
            if "trial" in response.text.lower():
                await broadcast_trial_balance_from_headers(response, force_exhausted=True)
                raise ValueError(
                    "Included Basil Cloud credit exhausted -- please sign in to continue "
                    "with Basil Cloud or use your own keys"
                )
            raise ValueError("Payment required -- please add a payment method")
        if response.status_code == 403:
            raise ValueError("Subscription inactive -- please update your subscription")
        if response.status_code >= 400:
            raise ValueError(
                f"Auth service transcription error ({response.status_code}): {response.text}"
            )

        await broadcast_trial_balance_from_headers(response)

        transcribed_text = response.text.strip()
        logger.info(
            "Auth-proxy transcription complete (%s): %s chars",
            auth_label,
            len(transcribed_text),
        )
        return transcribed_text
