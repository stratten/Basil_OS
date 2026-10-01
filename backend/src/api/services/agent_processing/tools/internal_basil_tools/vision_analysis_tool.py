"""
Vision Analysis Tool for Agent LLM Sub-Calls

Provides a tool that lets the agent send images to the running model's vision
capabilities for analysis. Uses the same auth pipeline (auth proxy / own keys)
that powers the agent's own reasoning, so it respects the user's model choice
and API key preference automatically.

This is a *generic* multimodal sub-call facility: book covers, screenshots,
receipts, diagrams, photos — anything the model can see.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from api.services.agent_processing.tools.vision.backend_resolver import VisionBackend

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)


# Why this slim:
# - The full description is mostly USE/DO NOT USE prose plus an arg list
#   (already in VisionAnalysisInput) and a 'batch many images' tip. The
#   single load-bearing fact is 'do NOT write Python / OCR for image
#   understanding - call this tool instead'; that misroute is the most
#   common one for cloud models with code-execution leanings (and is a
#   total dead end for local models that have no python tool at all).
# - KEEPS the 'native vision capabilities, do NOT reimplement with code/
#   OCR' rule, the file-format hint (png/jpg/jpeg/gif/webp - the agent
#   needs this to validate paths before calling), and the 'absolute
#   paths' invariant (relative paths fail silently).
# - DROPS the use-case enumeration (book titles, screenshots, receipts,
#   diagrams - any of those is obviously a vision task without listing)
#   and the 'batch by repeated calls' tip (an implementation detail that
#   does not affect routing).
SLIM_DESCRIPTION = (
    "analyze_with_vision(file_paths: list[str], prompt: str) - send one "
    "or more local image files to the model's NATIVE vision; supported "
    "formats: png, jpg, jpeg, gif, webp. file_paths must be ABSOLUTE "
    "paths. Use this for ANY visual inspection task (reading text in "
    "images, identifying objects, describing diagrams). Do NOT write "
    "Python / OCR / shell scripts to read images - this tool is the "
    "vision capability."
)

# Supported image extensions and their MIME types
SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Reject individual files larger than this (early gate for absurdly large files).
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB

# Anthropic enforces a 5 MB limit on base64-encoded image payloads.
# We target 4.5 MB to leave headroom.  OpenAI is more generous (~20 MB)
# but the quality difference is negligible for vision analysis, so we use
# the strictest provider limit as the universal ceiling.
MAX_BASE64_BYTES = 4_500_000  # ~4.5 MB

# Anthropic also enforces a maximum pixel dimension (either side).
MAX_IMAGE_DIMENSION = 8000


class VisionAnalysisInput(BaseModel):
    """Input schema for the analyze_with_vision tool."""

    file_paths: List[str] = Field(
        description=(
            "List of absolute file paths to images on disk to analyze. "
            "Supported formats: png, jpg, jpeg, gif, webp. "
            "Each file must be under 20 MB."
        )
    )
    prompt: str = Field(
        description=(
            "The analysis instruction to send alongside the image(s). "
            "Be specific about what information you want extracted. "
            "Example: 'What book title and author are visible in this image?'"
        )
    )


def _estimate_base64_size(raw_byte_count: int) -> int:
    """Return the base64-encoded size for a given raw byte count."""
    return (raw_byte_count + 2) // 3 * 4


def _resize_image_to_fit(
    raw: bytes, mime: str, filename: str
) -> Tuple[bytes, str]:
    """Resize / compress an image so it satisfies both API constraints:

    1. Base64-encoded payload ≤ ``MAX_BASE64_BYTES``
    2. Neither dimension exceeds ``MAX_IMAGE_DIMENSION``

    Strategy:
      - Clamp dimensions to ``MAX_IMAGE_DIMENSION`` first.
      - Convert opaque PNGs → JPEG (typical 5-10× reduction for photos).
      - Progressively downscale (75 % per pass) until base64 fits.

    Returns:
        ``(processed_bytes, final_mime_type)``

    Raises:
        ValueError: If the image cannot be shrunk enough after all attempts.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    original_w, original_h = img.size

    # ---- 1. Clamp to MAX_IMAGE_DIMENSION ----
    if original_w > MAX_IMAGE_DIMENSION or original_h > MAX_IMAGE_DIMENSION:
        ratio = min(MAX_IMAGE_DIMENSION / original_w,
                    MAX_IMAGE_DIMENSION / original_h)
        new_w = max(1, int(original_w * ratio))
        new_h = max(1, int(original_h * ratio))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.info(
            f"📷 Clamped {filename} dimensions: "
            f"{original_w}×{original_h} → {new_w}×{new_h} "
            f"(max {MAX_IMAGE_DIMENSION}px)"
        )

    # ---- 2. Opportunistic format conversion ----
    # PNGs without meaningful transparency are *much* smaller as JPEG.
    output_format = "PNG"
    output_mime = mime
    if mime == "image/png":
        has_alpha = img.mode in ("RGBA", "LA", "PA")
        alpha_used = False
        if has_alpha:
            alpha = img.getchannel("A")
            alpha_min = alpha.getextrema()[0]
            alpha_used = alpha_min < 254
        if not alpha_used:
            img = img.convert("RGB")
            output_format = "JPEG"
            output_mime = "image/jpeg"
    elif mime in ("image/jpeg", "image/webp"):
        output_format = mime.split("/")[-1].upper()
        if output_format == "WEBP":
            output_format = "WEBP"
        # Ensure RGB for JPEG
        if output_format == "JPEG" and img.mode != "RGB":
            img = img.convert("RGB")

    # ---- 3. Progressive downscale loop for base64 size ----
    quality = 85
    scale = 1.0

    for attempt in range(8):
        cur_w = max(1, int(img.width * scale))
        cur_h = max(1, int(img.height * scale))
        resized = img.resize((cur_w, cur_h), Image.LANCZOS) if scale < 1.0 else img

        buf = io.BytesIO()
        if output_format == "JPEG":
            resized.save(buf, format="JPEG", quality=quality, optimize=True)
        elif output_format == "WEBP":
            resized.save(buf, format="WEBP", quality=quality)
        else:
            resized.save(buf, format="PNG", optimize=True)

        result = buf.getvalue()
        b64_size = _estimate_base64_size(len(result))

        if b64_size <= MAX_BASE64_BYTES:
            logger.info(
                f"📷 Auto-resized {filename}: "
                f"{original_w}×{original_h} → {cur_w}×{cur_h}, "
                f"{len(result) / 1024:.0f} KB "
                f"(was {len(raw) / 1024:.0f} KB, format={output_format})"
            )
            return result, output_mime

        # Shrink further on next pass
        scale *= 0.75
        quality = max(50, quality - 5)

    raise ValueError(
        f"Could not resize {filename} to fit the "
        f"{MAX_BASE64_BYTES / 1_000_000:.1f} MB base64 API limit "
        f"after {attempt + 1} attempts"
    )


def _load_and_encode_image(file_path: str) -> dict:
    """Read an image from disk and return an OpenAI-format image_url content block.

    If the image would exceed the API provider's base64 size limit or
    dimension cap, it is automatically resized / compressed to fit.

    Returns:
        Dict with keys ``type``, ``image_url`` suitable for inclusion in a
        multimodal ``HumanMessage.content`` list.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the file type is unsupported or the file is too large.
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a regular file: {path}")

    ext = path.suffix.lower()
    mime = SUPPORTED_IMAGE_TYPES.get(ext)
    if mime is None:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES.keys()))
        raise ValueError(
            f"Unsupported image type '{ext}' for {path.name}. "
            f"Supported: {supported}"
        )

    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image too large: {path.name} is {size / (1024*1024):.1f} MB "
            f"(max {MAX_IMAGE_BYTES / (1024*1024):.0f} MB)"
        )

    raw = path.read_bytes()

    # ---- auto-resize if base64 would exceed API limit ----
    b64_size = _estimate_base64_size(len(raw))
    needs_resize = b64_size > MAX_BASE64_BYTES

    # Also check pixel dimensions (requires opening with Pillow)
    if not needs_resize:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as img:
                w, h = img.size
            if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
                needs_resize = True
                logger.info(
                    f"📷 Image {path.name} exceeds {MAX_IMAGE_DIMENSION}px "
                    f"dimension cap ({w}×{h}) — auto-resizing"
                )
        except Exception:
            pass  # If we can't check dimensions, proceed and let the API reject if needed

    if needs_resize:
        if b64_size > MAX_BASE64_BYTES:
            logger.info(
                f"📷 Image {path.name} would be {b64_size / 1_000_000:.1f} MB "
                f"in base64 (limit {MAX_BASE64_BYTES / 1_000_000:.1f} MB) "
                f"— auto-resizing"
            )
        raw, mime = _resize_image_to_fit(raw, mime, path.name)

    b64 = base64.b64encode(raw).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    logger.info(f"📷 Loaded image: {path.name} ({len(raw) / 1024:.0f} KB, {mime})")

    return {
        "type": "image_url",
        "image_url": {"url": data_url},
    }


def create_vision_analysis_tool(
    coordinator: Any,
    *,
    vision_backend: Optional[VisionBackend] = None,
    models_dir: Optional[Path] = None,
    local_vision_model_id: Optional[str] = None,
    profile=None,
) -> StructuredTool:
    """Factory: create the ``analyze_with_vision`` tool with the coordinator's
    LLM credentials captured in a closure.

    The tool creates a **fresh** LangChain LLM instance (no tools bound). For
    cloud/API agents this uses ``create_langchain_llm`` (same auth as the agent).
    For local Qwen2.5-VL fallback it loads the GGUF + mmproj pair from disk.

    Args:
        coordinator: ``WorkflowCoordinator`` with an initialized ``_llm_model``.
        vision_backend: Which backend to use (native agent model vs local Qwen VL).
        models_dir: Basil models directory (required for local Qwen VL).
        local_vision_model_id: Registry id for the local vision pair.
        profile: Optional RuntimeModelProfile carrying the active tool_rendering value.
                 Under a slim profile the description is swapped to ``SLIM_DESCRIPTION``;
                 otherwise the full description (defined inline below) flows through
                 unchanged.

    Returns:
        A ``StructuredTool`` ready to be appended to the agent's tool list.
    """
    # Import here to avoid circular imports at module level
    from ...lifecycle.execution_graph.agent_executor_factory import create_langchain_llm
    from api.services.agent_processing.tools.vision.backend_resolver import VisionBackend

    vb = vision_backend or VisionBackend.NATIVE

    # Lazy-init: build LangChain LLM on first use so tool registration never fails
    # the whole agent workflow if LLM wiring has a transient issue.
    _vision_state: Dict[str, Any] = {"llm": None, "init_error": None}

    def _ensure_vision_llm() -> None:
        if _vision_state["llm"] is not None or _vision_state["init_error"]:
            return
        try:
            if vb == VisionBackend.NATIVE:
                _vision_state["llm"] = create_langchain_llm(coordinator)
                logger.info("👁️ Vision analysis LLM created successfully (native)")
            elif vb == VisionBackend.LOCAL_QWEN_VL:
                from api.services.agent_processing.tools.vision.local_qwen_vl_loader import (
                    create_local_qwen_vl_langchain_adapter,
                )

                if not models_dir or not local_vision_model_id:
                    raise RuntimeError(
                        "Local vision backend requires models_dir and local_vision_model_id"
                    )
                _vision_state["llm"] = create_local_qwen_vl_langchain_adapter(
                    models_dir, local_vision_model_id
                )
                logger.info("👁️ Vision analysis LLM created successfully (local Qwen2.5-VL)")
            else:
                raise RuntimeError(f"Unsupported vision backend: {vb}")
        except Exception as exc:
            _vision_state["init_error"] = str(exc)
            logger.warning(f"👁️ Vision LLM unavailable (tool will return error): {exc}")

    async def _analyze_with_vision_impl(
        file_paths: List[str],
        prompt: str,
    ) -> str:
        """Send one or more images to the model's vision capabilities for analysis.

        Use this for any task that requires *looking at* an image: identifying
        book titles, reading text in photos, describing diagrams, extracting
        data from screenshots, etc.

        Args:
            file_paths: Absolute paths to image files on disk.
            prompt: What to analyze or extract from the image(s).

        Returns:
            The model's text response describing what it sees.
        """
        _ensure_vision_llm()
        vision_llm = _vision_state["llm"]
        init_err = _vision_state["init_error"]

        # ---- guard: LLM must be available ----
        if vision_llm is None:
            detail = init_err or "unknown_error"
            if vb == VisionBackend.LOCAL_QWEN_VL:
                return (
                    "Vision analysis uses the local Qwen2.5-VL model but it "
                    f"failed to load. Details: {detail}"
                )
            return (
                "Vision analysis is not available with the current model/API "
                "key configuration. Use a multimodal-capable cloud model "
                "(e.g. Claude with vision, GPT-4o / GPT-5 family with vision) "
                "or enable local Qwen2.5-VL fallback in Settings when both GGUF "
                f"files are installed. Details: {detail}"
            )

        if not file_paths:
            return "Error: No file paths provided. Please supply at least one image path."

        # ---- load and encode images ----
        content_blocks: list = [{"type": "text", "text": prompt}]
        loaded_count = 0
        errors: list = []

        for fp in file_paths:
            try:
                block = _load_and_encode_image(fp)
                content_blocks.append(block)
                loaded_count += 1
            except (FileNotFoundError, ValueError) as exc:
                error_msg = str(exc)
                errors.append(error_msg)
                logger.warning(f"👁️ Skipping image: {error_msg}")

        if loaded_count == 0:
            error_detail = "; ".join(errors)
            return (
                f"Error: Could not load any images. {error_detail}. "
                "Check that the file paths are correct and the files are "
                "supported image types (png, jpg, jpeg, gif, webp)."
            )

        # ---- call the model ----
        logger.info(
            f"👁️ Vision analysis: sending {loaded_count} image(s) with prompt "
            f"({len(prompt)} chars) to model"
        )

        try:
            message = HumanMessage(content=content_blocks)
            response = await vision_llm.ainvoke([message])

            # Extract text from the AIMessage response
            result_text = response.content if hasattr(response, "content") else str(response)

            logger.info(
                f"👁️ Vision analysis complete: received {len(result_text)} chars"
            )

            # Prepend any per-file errors so the agent knows which files failed
            if errors:
                skipped = "\n".join(f"  - {e}" for e in errors)
                result_text = (
                    f"Note: {len(errors)} file(s) could not be loaded and were skipped:\n"
                    f"{skipped}\n\n"
                    f"Analysis of {loaded_count} successfully loaded image(s):\n{result_text}"
                )

            return result_text

        except Exception as exc:
            logger.error(f"👁️ Vision analysis LLM call failed: {exc}", exc_info=True)
            return (
                f"Vision analysis failed: {exc}. "
                "This may be a transient API error — consider retrying. "
                "If the error persists, the current model may not support vision."
            )

    full_description = (
        "Analyze one or more images using the model's built-in vision capabilities. "
        "Accepts local file paths to images (png, jpg, jpeg, gif, webp) and a text prompt "
        "describing what to look for or extract.\n"
        "\n"
        "USE THIS TOOL for any task that requires visually inspecting images:\n"
        "  - Identifying book titles, authors, or text in photos\n"
        "  - Reading text from screenshots, receipts, or documents\n"
        "  - Describing diagrams, charts, or visual content\n"
        "  - Extracting structured data from visual sources\n"
        "\n"
        "DO NOT write Python scripts or use OCR for image understanding — this tool "
        "gives you direct access to the model's vision capabilities through the same "
        "API the user is already authenticated with.\n"
        "\n"
        "For batch processing many images, call this tool repeatedly (one or a few "
        "images per call) and aggregate the results yourself.\n"
        "\n"
        "Args:\n"
        "  file_paths: List of absolute file paths to images on disk\n"
        "  prompt: Analysis instruction (e.g. 'What book title and author are visible?')\n"
        "\n"
        "Returns: The model's text description/analysis of the image(s)."
    )
    chosen_description = select_description_for_profile(
        profile, full_description, SLIM_DESCRIPTION
    )

    tool = StructuredTool(
        name="analyze_with_vision",
        func=_analyze_with_vision_impl,      # sync fallback (LangChain requires)
        coroutine=_analyze_with_vision_impl,  # async — actually used at runtime
        args_schema=VisionAnalysisInput,
        description=chosen_description,
    )

    return tool
