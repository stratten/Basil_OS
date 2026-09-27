"""
OpenAI File Handler (provider-specific)

Co-located with other file-system handlers (e.g., Anthropic) under
direct_application_interactions/file_system to avoid scattering provider
integration code across unrelated folders.

Responsibilities:
- Upload local files via OpenAI Files API and return file_id
- Build provider-appropriate payloads referencing file_id
- Provide a safe text-only fallback with a capped budget (no persistence)
"""

from __future__ import annotations

import logging
import os
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import asyncio

logger = logging.getLogger(__name__)

# Prefer central API key manager when available
try:
    from config.api_keys import get_api_key as get_managed_api_key  # type: ignore
except Exception:
    get_managed_api_key = None  # type: ignore


@dataclass
class OpenAIUploadResult:
    success: bool
    file_id: Optional[str] = None
    filename: Optional[str] = None
    byte_size: Optional[int] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None


class OpenAIFileHandler:
    MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
    TEXT_FALLBACK_CHAR_BUDGET = 16_000

    def __init__(self, api_key: Optional[str] = None):
        # Resolve API key with precedence: explicit > key manager > env var
        resolved_key: Optional[str] = api_key
        if resolved_key is None and get_managed_api_key is not None:
            try:
                resolved_key = get_managed_api_key("openai")
                logger.info("OpenAIFileHandler: Loaded API key via key manager")
            except Exception:
                resolved_key = None
        if resolved_key is None:
            resolved_key = os.getenv("OPENAI_API_KEY")
            if resolved_key:
                logger.info("OpenAIFileHandler: Loaded API key from environment")
            else:
                logger.warning("OpenAIFileHandler: No OpenAI API key available from key manager or environment")
        self.api_key = resolved_key
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # type: ignore
            if not self.api_key:
                # Late resolution attempt for long-lived processes
                if get_managed_api_key is not None:
                    try:
                        self.api_key = get_managed_api_key("openai")
                        logger.info("OpenAIFileHandler: Resolved API key via key manager at client init")
                    except Exception:
                        self.api_key = os.getenv("OPENAI_API_KEY")
                else:
                    self.api_key = os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise RuntimeError("OpenAI API key is not configured. Set it via the key manager or OPENAI_API_KEY env var.")
            self._client = OpenAI(api_key=self.api_key)
            return self._client
        except Exception as e:
            logger.error(f"OpenAI client init failed: {e}")
            raise

    def _guess_mime_type(self, path: Path) -> str:
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "application/octet-stream"

    def upload_file(self, file_path: str, purpose: str = "assistants") -> OpenAIUploadResult:
        try:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                return OpenAIUploadResult(success=False, error=f"File not found: {file_path}")

            byte_size = path.stat().st_size
            if byte_size > self.MAX_UPLOAD_SIZE_BYTES:
                return OpenAIUploadResult(
                    success=False,
                    error=(
                        f"File too large ({byte_size} bytes). Max allowed: {self.MAX_UPLOAD_SIZE_BYTES} bytes"
                    ),
                )

            mime_type = self._guess_mime_type(path)
            client = self._get_client()

            with open(path, "rb") as f:
                uploaded = client.files.create(file=f, purpose=purpose)

            file_id = getattr(uploaded, "id", None) or (uploaded.get("id") if isinstance(uploaded, dict) else None)
            if not file_id:
                return OpenAIUploadResult(success=False, error="Upload returned no file id")

            logger.info(f"✅ OpenAI file upload succeeded: {file_id} ({path.name}, {byte_size} bytes)")
            return OpenAIUploadResult(
                success=True,
                file_id=file_id,
                filename=path.name,
                byte_size=byte_size,
                mime_type=mime_type,
            )

        except Exception as e:
            logger.error(f"OpenAI file upload failed: {e}")
            return OpenAIUploadResult(success=False, error=str(e))

    def prepare_assistants_request(self, instructions: str, file_ids: List[str], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "instructions": instructions,
            "attachments": [{"file_id": fid} for fid in file_ids],
        }
        if extra:
            payload.update(extra)
        return payload

    def prepare_responses_request(self, prompt: str, file_ids: List[str], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Build a Responses API payload that references files via input content blocks.
        Format:
        input: [
          {
            role: "user",
            content: [
              { type: "input_text", text: prompt },
              { type: "input_file", file_id: "file_..." }, ...
            ]
          }
        ]
        """
        content_blocks: List[Dict[str, Any]] = [
            {"type": "input_text", "text": prompt}
        ]
        for fid in file_ids:
            content_blocks.append({"type": "input_file", "file_id": fid})

        payload: Dict[str, Any] = {
            "input": [
                {
                    "role": "user",
                    "content": content_blocks,
                }
            ]
        }
        if extra:
            payload.update(extra)
        return payload

    def text_fallback_with_budget(self, extracted_text: str, max_chars: Optional[int] = None) -> str:
        if not extracted_text:
            return ""
        budget = max_chars if isinstance(max_chars, int) and max_chars > 0 else self.TEXT_FALLBACK_CHAR_BUDGET
        return extracted_text[:budget]


    async def generate_response_with_files(
        self,
        *,
        prompt: str,
        file_paths: List[str],
        model: str,
        extra: Optional[Dict[str, Any]] = None,
        extracted_text_fallback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload files to OpenAI, get file_ids, and request a response that consumes file_ids directly.
        Falls back to capped text if uploads or API route are unavailable.
        """
        # 1) Upload files concurrently
        async def _upload(path: str) -> OpenAIUploadResult:
            return await asyncio.to_thread(self.upload_file, path)

        upload_results: List[OpenAIUploadResult] = []
        try:
            upload_results = await asyncio.gather(*[_upload(p) for p in file_paths])
        except Exception as e:
            logger.error(f"OpenAI uploads failed: {e}")

        file_ids: List[str] = [r.file_id for r in upload_results if r.success and r.file_id]
        if not file_ids:
            logger.warning("OpenAI file_id path unavailable; using text fallback if provided")
            fallback_text = self.text_fallback_with_budget(extracted_text_fallback or "")
            if not fallback_text:
                return {"error": "OpenAI file upload failed and no text fallback available."}
            # Use plain text generation via Responses API
            try:
                client = self._get_client()
                resp = await asyncio.to_thread(
                    lambda: client.responses.create(model=model, input=prompt + "\n\n" + fallback_text)
                )
                # Extract final text
                output_text = getattr(resp, "output_text", None)
                if not output_text and isinstance(resp, dict):
                    output_text = resp.get("output_text")
                if not output_text:
                    # conservative extraction from generic structure
                    output_text = str(resp)
                return {"suggestion": output_text, "used_fallback_text": True}
            except Exception as e:
                logger.error(f"OpenAI Responses (text fallback) failed: {e}")
                return {"error": f"OpenAI text fallback failed: {e}"}

        # 2) Call Responses API with attachments (preferred)
        try:
            payload = self.prepare_responses_request(prompt=prompt, file_ids=file_ids, extra=extra)
            client = self._get_client()
            resp = await asyncio.to_thread(lambda: client.responses.create(model=model, **payload))

            output_text = getattr(resp, "output_text", None)
            if not output_text and isinstance(resp, dict):
                output_text = resp.get("output_text")
            if not output_text:
                # conservative extraction from generic structure
                output_text = str(resp)
            return {"suggestion": output_text, "uploaded_files": len(file_ids)}
        except Exception as e:
            logger.warning(f"OpenAI Responses with attachments failed, falling back to text: {e}")
            fallback_text = self.text_fallback_with_budget(extracted_text_fallback or "")
            if not fallback_text:
                return {"error": f"OpenAI attachments route failed and no text fallback available: {e}"}
            try:
                client = self._get_client()
                resp = await asyncio.to_thread(
                    lambda: client.responses.create(model=model, input=prompt + "\n\n" + fallback_text)
                )
                output_text = getattr(resp, "output_text", None)
                if not output_text and isinstance(resp, dict):
                    output_text = resp.get("output_text")
                if not output_text:
                    output_text = str(resp)
                return {"suggestion": output_text, "used_fallback_text": True, "upload_error": str(e)}
            except Exception as e2:
                logger.error(f"OpenAI Responses fallback failed: {e2}")
                return {"error": f"OpenAI responses failed: {e2}"}

    async def stream_response_with_files(
        self,
        *,
        prompt: str,
        file_paths: List[str],
        model: str,
        on_token: Callable[[str], None],
        extra: Optional[Dict[str, Any]] = None,
        extracted_text_fallback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Stream a response using OpenAI Responses API with file attachments.
        Tokens are passed to on_token as they arrive. Returns the final text.
        Falls back to capped text if attachments route is unavailable.
        """
        # Upload first
        async def _upload(path: str) -> OpenAIUploadResult:
            return await asyncio.to_thread(self.upload_file, path)

        upload_results: List[OpenAIUploadResult] = []
        try:
            upload_results = await asyncio.gather(*[_upload(p) for p in file_paths])
        except Exception as e:
            logger.error(f"OpenAI uploads failed: {e}")

        file_ids: List[str] = [r.file_id for r in upload_results if r.success and r.file_id]

        client = self._get_client()

        def _stream_with_payload(payload: Dict[str, Any]) -> str:
            final_text_parts: List[str] = []
            try:
                with client.responses.stream(model=model, **payload) as stream:
                    for event in stream:
                        # Try to handle common event shapes; be liberal
                        try:
                            etype = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
                        except Exception:
                            etype = None
                        if etype in {"response.output_text.delta", "text.delta", "delta"}:
                            delta = getattr(event, "delta", None)
                            if delta is None and isinstance(event, dict):
                                delta = event.get("delta") or event.get("text") or event.get("content")
                            if isinstance(delta, str) and delta:
                                on_token(delta)
                                final_text_parts.append(delta)
                        elif etype in {"response.completed", "response.completed.success", "done"}:
                            # End of stream marker
                            break
                return "".join(final_text_parts)
            except Exception as e:
                logger.warning(f"OpenAI stream failed: {e}")
                raise

        # Prefer attachments route
        if file_ids:
            try:
                payload = self.prepare_responses_request(prompt=prompt, file_ids=file_ids, extra=extra)
                final_text = await asyncio.to_thread(_stream_with_payload, payload)
                return {"suggestion": final_text, "uploaded_files": len(file_ids)}
            except Exception as e:
                logger.warning(f"OpenAI stream with attachments failed, falling back to text: {e}")

        # Fallback: stream text-only (simulate by chunking non-streamed response if SDK lacks stream)
        fallback_text = self.text_fallback_with_budget(extracted_text_fallback or "")
        try:
            resp = await asyncio.to_thread(lambda: client.responses.create(model=model, input=prompt + "\n\n" + fallback_text))
            output_text = getattr(resp, "output_text", None)
            if not output_text and isinstance(resp, dict):
                output_text = resp.get("output_text")
            if not output_text:
                output_text = str(resp)
            # Emit in coarse chunks to UI if we had no real streaming path
            chunk_size = 200
            for i in range(0, len(output_text), chunk_size):
                on_token(output_text[i : i + chunk_size])
            return {"suggestion": output_text, "used_fallback_text": True}
        except Exception as e:
            logger.error(f"OpenAI text-only fallback failed: {e}")
            return {"error": f"OpenAI text-only fallback failed: {e}"}

