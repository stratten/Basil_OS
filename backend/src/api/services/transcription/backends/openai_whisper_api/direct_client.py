"""Direct OpenAI client wrapper for transcription requests."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import uuid
from pathlib import Path
from time import monotonic
from typing import Any, Dict, List, Optional, Sequence

from .request_policy import (
    CONNECTION_ERROR_USER_MESSAGE,
    TranscriptionAttemptPolicy,
    build_transcription_attempt_policies,
    estimate_wav_duration_seconds,
    is_connection_error,
    should_retry_transcription_error,
)
from .response_parsing import extract_timestamped_segments

logger = logging.getLogger(__name__)


def _new_request_id() -> str:
    return uuid.uuid4().hex[:8]


def _request_log_context(
    kind: str,
    model: Optional[str],
    byte_count: int,
    request_id: str,
) -> str:
    return f"request_id={request_id} kind={kind} model={model} bytes={byte_count}"


class DirectOpenAITranscriptionClient:
    """Own-key OpenAI transcription client."""

    def __init__(self, api_model_name: Optional[str]) -> None:
        self.api_model_name = api_model_name
        self._client = None

    def unload(self) -> None:
        """Release the cached OpenAI client reference."""
        self._client = None

    def _get_client(self):
        """Lazily create the OpenAI client with the user's own API key."""
        if self._client is not None:
            return self._client

        from config.api_keys import get_api_key
        api_key = get_api_key("openai")
        if not api_key:
            raise ValueError(
                "No OpenAI API key configured. Set one in Settings > Models > API Models."
            )

        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, max_retries=0)
        return self._client

    async def transcribe_text(
        self,
        wav_bytes: bytes,
        suffix: str,
        language: Optional[str] = None,
        *,
        formatting_prompt: Optional[str] = None,
    ) -> str:
        """Transcribe directly via the OpenAI API using the user's own key."""
        client = self._get_client()

        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(wav_bytes)
            tmp.flush()
            tmp.close()

            kwargs: Dict[str, Any] = {
                "model": self.api_model_name,
                "response_format": "text",
            }
            if language:
                kwargs["language"] = language
            if formatting_prompt:
                kwargs["prompt"] = formatting_prompt

            attempt_policies = build_transcription_attempt_policies(
                audio_duration_seconds=estimate_wav_duration_seconds(wav_bytes),
            )
            context = _request_log_context(
                "text",
                self.api_model_name,
                len(wav_bytes),
                _new_request_id(),
            )
            response = await self._run_openai_transcription_request(
                client,
                tmp.name,
                kwargs,
                context=context,
                attempt_policies=attempt_policies,
            )

            if isinstance(response, str):
                transcribed_text = response.strip()
            else:
                transcribed_text = response.text.strip()

            logger.info(
                "OpenAI API transcription complete (own_keys): %s chars",
                len(transcribed_text),
            )
            return transcribed_text

        finally:
            Path(tmp.name).unlink(missing_ok=True)

    async def transcribe_segments(
        self,
        wav_bytes: bytes,
        suffix: str,
        language: Optional[str] = None,
        *,
        formatting_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Request segment timestamps from OpenAI's transcription endpoint."""
        client = self._get_client()

        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(wav_bytes)
            tmp.flush()
            tmp.close()

            kwargs: Dict[str, Any] = {
                "model": self.api_model_name,
                "response_format": "verbose_json",
                "timestamp_granularities": ["segment"],
            }
            if language:
                kwargs["language"] = language
            if formatting_prompt:
                kwargs["prompt"] = formatting_prompt

            attempt_policies = build_transcription_attempt_policies(
                audio_duration_seconds=estimate_wav_duration_seconds(wav_bytes),
            )
            context = _request_log_context(
                "segments",
                self.api_model_name,
                len(wav_bytes),
                _new_request_id(),
            )
            response = await self._run_openai_transcription_request(
                client,
                tmp.name,
                kwargs,
                context=context,
                attempt_policies=attempt_policies,
            )

            segments = extract_timestamped_segments(response)
            if not segments:
                raw_segments = (
                    response.get("segments")
                    if isinstance(response, dict)
                    else getattr(response, "segments", None)
                )
                if raw_segments:
                    raise ValueError(
                        f"API model {self.api_model_name} returned invalid timestamped segments."
                    )
                logger.info(
                    "OpenAI API timestamped transcription returned no segments: "
                    "%s response_type=%s",
                    context,
                    type(response).__name__,
                )
                return []

            logger.info(
                "OpenAI API timestamped transcription complete: %s segments",
                len(segments),
            )
            return segments

        except TypeError as exc:
            raise ValueError(
                f"API model {self.api_model_name} does not support timestamped segment output "
                "with the installed OpenAI client."
            ) from exc
        except Exception as exc:
            if getattr(exc, "status_code", None) == 413 or "413" in str(exc):
                raise ValueError(
                    "OpenAI rejected a meeting audio chunk because it exceeded the provider upload limit. "
                    "Basil already split the recording using its configured safety budget; reduce the API "
                    "chunk budget or use a local transcription model for this meeting."
                ) from exc
            raise
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    async def _run_openai_transcription_request(
        self,
        client: Any,
        audio_file_path: str,
        kwargs: Dict[str, Any],
        *,
        context: str,
        attempt_policies: Sequence[TranscriptionAttemptPolicy],
    ) -> Any:
        """Run the synchronous OpenAI SDK call without blocking the event loop."""
        queued_at = monotonic()
        audio_duration = (
            attempt_policies[0].audio_duration_seconds
            if attempt_policies
            else None
        )
        logger.info(
            "OpenAI transcription request queued: %s attempts=%s audio_duration=%s",
            context,
            len(attempt_policies),
            f"{audio_duration:.2f}s" if audio_duration is not None else "unknown",
        )

        def run_blocking_request(
            configured_client: Any,
            policy: TranscriptionAttemptPolicy,
        ) -> Any:
            worker_started_at = monotonic()
            thread_id = threading.get_ident()
            logger.info(
                "OpenAI transcription worker started: %s attempt=%s/%s read_timeout=%.2fs thread=%s",
                context,
                policy.attempt_number,
                policy.max_attempts,
                policy.read_timeout_seconds,
                thread_id,
            )
            try:
                with open(audio_file_path, "rb") as audio_file:
                    response = configured_client.audio.transcriptions.create(
                        **{**kwargs, "file": audio_file}
                    )
                logger.info(
                    "OpenAI transcription worker completed: %s attempt=%s/%s thread=%s worker_wall=%.2fs",
                    context,
                    policy.attempt_number,
                    policy.max_attempts,
                    thread_id,
                    monotonic() - worker_started_at,
                )
                return response
            except Exception as exc:
                logger.error(
                    "OpenAI transcription worker failed: %s attempt=%s/%s thread=%s worker_wall=%.2fs error_type=%s error=%s",
                    context,
                    policy.attempt_number,
                    policy.max_attempts,
                    thread_id,
                    monotonic() - worker_started_at,
                    type(exc).__name__,
                    exc,
                )
                raise

        last_exc: Optional[BaseException] = None
        try:
            for policy in attempt_policies:
                configured_client = client.with_options(
                    timeout=policy.to_httpx_timeout(),
                    max_retries=0,
                )
                try:
                    response = await asyncio.to_thread(
                        run_blocking_request,
                        configured_client,
                        policy,
                    )
                    logger.info(
                        "OpenAI transcription request completed: %s attempt=%s/%s total_wall=%.2fs",
                        context,
                        policy.attempt_number,
                        policy.max_attempts,
                        monotonic() - queued_at,
                    )
                    return response
                except Exception as exc:
                    last_exc = exc
                    retryable = should_retry_transcription_error(exc)
                    has_next_attempt = policy.attempt_number < policy.max_attempts
                    logger.warning(
                        "OpenAI transcription attempt failed: %s attempt=%s/%s retryable=%s has_next_attempt=%s error_type=%s error=%s",
                        context,
                        policy.attempt_number,
                        policy.max_attempts,
                        retryable,
                        has_next_attempt,
                        type(exc).__name__,
                        exc,
                    )
                    if retryable and has_next_attempt:
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("OpenAI transcription request had no configured attempts")
        except Exception as exc:
            logger.error(
                "OpenAI transcription request failed: %s total_wall=%.2fs error_type=%s error=%s",
                context,
                monotonic() - queued_at,
                type(exc).__name__,
                exc,
            )
            if _is_timeout_error(exc):
                raise TimeoutError(
                    "OpenAI transcription timed out after 2 attempts. "
                    "The audio was saved and can be retried from Transcription History."
                ) from exc
            if is_connection_error(exc):
                raise ConnectionError(CONNECTION_ERROR_USER_MESSAGE) from exc
            raise


def _is_timeout_error(exc: BaseException) -> bool:
    error_type_name = type(exc).__name__
    if error_type_name == "APITimeoutError":
        return True
    try:
        import httpx
        return isinstance(exc, httpx.TimeoutException)
    except Exception:
        return False
