"""
Service for processing files into model-ready content formats.

Reads files from disk and transforms them into the appropriate format
based on the target model's provider (Anthropic, OpenAI, Gemini, or local).
"""

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}
PDF_EXTENSION = "pdf"
TEXT_EXTENSIONS = {"txt", "md", "markdown", "csv", "json", "xml", "yaml", "yml", "log", "py", "js", "ts", "swift", "html", "css"}
DOCX_EXTENSIONS = {"docx", "doc"}

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"
PROVIDER_LOCAL = "local"


class DocumentProcessingService:
    """Reads files from disk and produces model-ready content."""

    def detect_provider(self, model) -> str:
        """Detect the provider type from a model instance."""
        from ...core.models.reasoning.claude_model import ClaudeModel
        from ...core.models.reasoning.openai_model import OpenAIModel
        from ...core.models.reasoning.gemini_model import GeminiModel
        from ...core.models.reasoning.auth_proxy_model import AuthProxyModel
        from ...core.models.reasoning.anthropic_compatible_model import AnthropicCompatibleModel
        from ...core.models.reasoning.openai_compatible_model import OpenAICompatibleModel

        if isinstance(model, ClaudeModel) or isinstance(model, AnthropicCompatibleModel):
            return PROVIDER_ANTHROPIC
        elif isinstance(model, OpenAIModel) or isinstance(model, OpenAICompatibleModel):
            return PROVIDER_OPENAI
        elif isinstance(model, GeminiModel):
            return PROVIDER_GEMINI
        elif isinstance(model, AuthProxyModel):
            return self._detect_auth_proxy_provider(model)
        else:
            return PROVIDER_LOCAL

    def _detect_auth_proxy_provider(self, model) -> str:
        """Detect the underlying provider for an AuthProxy model."""
        model_name = getattr(model, 'model_name', '') or ''
        model_name_lower = model_name.lower()
        if 'claude' in model_name_lower or 'anthropic' in model_name_lower:
            return PROVIDER_ANTHROPIC
        elif 'gpt' in model_name_lower or 'o1' in model_name_lower or 'o3' in model_name_lower:
            return PROVIDER_OPENAI
        elif 'gemini' in model_name_lower:
            return PROVIDER_GEMINI
        else:
            return PROVIDER_OPENAI

    async def process_files_for_model(
        self,
        file_paths: List[str],
        user_text: str,
        provider: str
    ) -> Dict[str, Any]:
        """
        Process files and produce model-ready content.

        Returns a dict with:
        - 'content': the formatted content (provider-specific structure or enhanced text)
        - 'method': 'multimodal' | 'text_prepend' | 'anthropic_files'
        - 'file_contents': for Anthropic path, the list of file dicts for chat_completion_streaming_with_files
        """
        if not file_paths:
            return {"content": user_text, "method": "none"}

        valid_paths = [p for p in file_paths if os.path.exists(p)]
        if not valid_paths:
            logger.warning(f"None of the {len(file_paths)} file paths exist")
            return {"content": user_text, "method": "none"}

        logger.info(f"Processing {len(valid_paths)} files for provider: {provider}")

        if provider == PROVIDER_ANTHROPIC:
            return await self._process_for_anthropic(valid_paths, user_text)
        elif provider == PROVIDER_OPENAI:
            return await self._process_for_openai(valid_paths, user_text)
        elif provider == PROVIDER_GEMINI:
            return await self._process_for_gemini(valid_paths, user_text)
        else:
            return await self._process_for_local(valid_paths, user_text)

    async def _process_for_anthropic(self, file_paths: List[str], user_text: str) -> Dict[str, Any]:
        """
        Prepare files for Anthropic/Claude API.
        Claude supports native base64 for images and PDFs.
        """
        file_contents = []
        text_parts = []

        for path in file_paths:
            ext = self._get_extension(path)
            if ext in IMAGE_EXTENSIONS or ext == PDF_EXTENSION:
                b64, mime = self._read_and_encode_base64(path)
                if b64:
                    file_contents.append({
                        "file_name": os.path.basename(path),
                        "file_type": ext,
                        "base64_content": b64,
                        "file_size": os.path.getsize(path),
                        "mime_type": mime
                    })
            elif ext in TEXT_EXTENSIONS:
                text = self._read_text_file(path)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")
            elif ext in DOCX_EXTENSIONS:
                text = await self._extract_docx_text(path)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")
            else:
                text = self._try_read_as_text(path)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")

        enhanced_text = user_text
        if text_parts:
            enhanced_text = "\n\n".join(text_parts) + "\n\n" + user_text

        if file_contents:
            return {
                "content": enhanced_text,
                "method": "anthropic_files",
                "file_contents": file_contents
            }
        else:
            return {"content": enhanced_text, "method": "text_prepend"}

    async def _process_for_openai(self, file_paths: List[str], user_text: str) -> Dict[str, Any]:
        """
        Prepare files for OpenAI API.
        OpenAI supports base64 images via image_url content parts.
        Documents are text-extracted.
        """
        content_parts = []
        text_parts = []

        for path in file_paths:
            ext = self._get_extension(path)
            if ext in IMAGE_EXTENSIONS:
                b64, mime = self._read_and_encode_base64(path)
                if b64:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}
                    })
            else:
                text = await self._extract_text_from_file(path, ext)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")

        if text_parts:
            prefix = "\n\n".join(text_parts)
            full_text = f"{prefix}\n\n{user_text}" if user_text else prefix
        else:
            full_text = user_text

        if content_parts:
            content_parts.insert(0, {"type": "text", "text": full_text})
            return {"content": content_parts, "method": "multimodal"}
        else:
            return {"content": full_text, "method": "text_prepend"}

    async def _process_for_gemini(self, file_paths: List[str], user_text: str) -> Dict[str, Any]:
        """
        Prepare files for Gemini API.
        Gemini supports inline_data for images and PDFs.
        """
        content_parts = []
        text_parts = []

        for path in file_paths:
            ext = self._get_extension(path)
            if ext in IMAGE_EXTENSIONS or ext == PDF_EXTENSION:
                b64, mime = self._read_and_encode_base64(path)
                if b64:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}
                    })
            else:
                text = await self._extract_text_from_file(path, ext)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")

        if text_parts:
            prefix = "\n\n".join(text_parts)
            full_text = f"{prefix}\n\n{user_text}" if user_text else prefix
        else:
            full_text = user_text

        if content_parts:
            content_parts.insert(0, {"type": "text", "text": full_text})
            return {"content": content_parts, "method": "multimodal"}
        else:
            return {"content": full_text, "method": "text_prepend"}

    async def _process_for_local(self, file_paths: List[str], user_text: str) -> Dict[str, Any]:
        """
        Prepare files for local models (text extraction only).
        """
        text_parts = []

        for path in file_paths:
            ext = self._get_extension(path)
            if ext in IMAGE_EXTENSIONS:
                text_parts.append(f"[Attached image: {os.path.basename(path)} - image content cannot be processed by this model]")
            else:
                text = await self._extract_text_from_file(path, ext)
                if text:
                    text_parts.append(f"--- {os.path.basename(path)} ---\n{text}")
                else:
                    text_parts.append(f"[Attached file: {os.path.basename(path)} - could not extract text content]")

        if text_parts:
            prefix = "\n\n".join(text_parts)
            enhanced = f"{prefix}\n\n{user_text}" if user_text else prefix
        else:
            enhanced = user_text

        return {"content": enhanced, "method": "text_prepend"}

    def _read_and_encode_base64(self, path: str) -> Tuple[Optional[str], str]:
        """Read file bytes and return (base64_string, mime_type)."""
        try:
            mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                data = f.read()
            return base64.b64encode(data).decode("utf-8"), mime_type
        except Exception as e:
            logger.error(f"Failed to read/encode file {path}: {e}")
            return None, "application/octet-stream"

    def _read_text_file(self, path: str) -> Optional[str]:
        """Read a text file and return its contents."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read text file {path}: {e}")
            return None

    def _try_read_as_text(self, path: str) -> Optional[str]:
        """Try to read an unknown file as text."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(1024 * 100)  # 100KB limit for unknown files
            return content
        except (UnicodeDecodeError, Exception):
            return None

    async def _extract_text_from_file(self, path: str, ext: str) -> Optional[str]:
        """Extract text from a file based on its extension."""
        if ext in TEXT_EXTENSIONS:
            return self._read_text_file(path)
        elif ext == PDF_EXTENSION:
            return await self._extract_pdf_text(path)
        elif ext in DOCX_EXTENSIONS:
            return await self._extract_docx_text(path)
        else:
            return self._try_read_as_text(path)

    async def _extract_pdf_text(self, path: str) -> Optional[str]:
        """Extract text from a PDF file."""
        try:
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pages = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                if pages:
                    return "\n\n".join(pages)
        except ImportError:
            logger.warning("PyPDF2 not installed, cannot extract PDF text")
        except Exception as e:
            logger.error(f"Failed to extract PDF text from {path}: {e}")

        try:
            import pdfplumber
            pages = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
            if pages:
                return "\n\n".join(pages)
        except ImportError:
            logger.warning("pdfplumber not installed, cannot extract PDF text")
        except Exception as e:
            logger.error(f"pdfplumber extraction failed for {path}: {e}")

        return None

    async def _extract_docx_text(self, path: str) -> Optional[str]:
        """Extract text from a DOCX file."""
        try:
            from docx import Document
            doc = Document(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            if paragraphs:
                return "\n\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed, cannot extract DOCX text")
        except Exception as e:
            logger.error(f"Failed to extract DOCX text from {path}: {e}")
        return None

    @staticmethod
    def _get_extension(path: str) -> str:
        return Path(path).suffix.lstrip(".").lower()

    @staticmethod
    def build_file_metadata(file_paths: List[str]) -> List[Dict[str, Any]]:
        """Build file reference metadata for storage in conversation message metadata."""
        refs = []
        for path in file_paths:
            try:
                refs.append({
                    "filename": os.path.basename(path),
                    "path": path,
                    "file_type": Path(path).suffix.lstrip(".").lower(),
                    "file_size": os.path.getsize(path)
                })
            except Exception as e:
                logger.warning(f"Could not build metadata for {path}: {e}")
        return refs
