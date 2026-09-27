"""Service for processing images with OCR and AI analysis."""

import asyncio
import pytesseract  # type: ignore[import-untyped]
from PIL import Image
import base64
import re
import time
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Set, Tuple, List
from datetime import datetime

from ...core.models.model_types import ModelCapability
from ...core.models.base_model import BaseAIModel
from ...core.services.model_service import ModelService, ModelNotFoundError
from ...core.logging.api_logger import api_logger
from ...core.services.file_storage_service import StorageService
from .image_models import OCRError, AnalysisError, ProcessingResponse, ActivityAnalysis
from ...core.models.model_invocation import call_model_with_prompt
from ...core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
from ...core.models.reasoning.streaming_contract import resolve_generation_budget
from ...core.models.reasoning.llama_cpp_model import LocalCompletionTelemetry
from ...settings import Settings, get_settings
from ...core.models.preferences import Preferences
from ...services.model_usage_service import ModelUsageService

# Preserve the established explicit request for cloud and unregistered models.
# Registry-backed local models resolve the activity_analysis workload budget instead.
ANALYSIS_MAX_TOKENS = 4096


def resolve_activity_analysis_output_tokens(model: BaseAIModel) -> int:
    """Return the effective activity-analysis budget for the selected model."""
    profile = resolve_runtime_model_profile(model)
    if (
        getattr(profile, "location", None) == "local"
        and getattr(profile, "handler", None) in {"llama_cpp", "huggingface"}
    ):
        return resolve_generation_budget(
            model,
            purpose="activity_analysis",
        ).effective_output_tokens
    return ANALYSIS_MAX_TOKENS

_ACTIVITY_GENERATION_CONTEXT_KEYS = frozenset(
    {"run_id", "activity_id", "analysis_model_id", "analysis_requested_tokens"}
)


def _telemetry_to_dict(telemetry: LocalCompletionTelemetry) -> Dict[str, Any]:
    finish_reason = telemetry.finish_reason.lower()
    return {
        "requested_output_tokens": telemetry.requested_output_tokens,
        "finish_reason": telemetry.finish_reason,
        "cap_hit": finish_reason in {"length", "max_tokens", "max_output_tokens"},
        "prompt_tokens": telemetry.prompt_tokens,
        "completion_tokens": telemetry.completion_tokens,
        "total_tokens": telemetry.total_tokens,
        "completion_token_source": telemetry.completion_token_source,
        "raw_completion_tokens": telemetry.raw_completion_tokens,
        "visible_completion_tokens": telemetry.visible_completion_tokens,
        "lock_wait_ms": telemetry.lock_wait_ms,
        "native_duration_ms": telemetry.native_duration_ms,
        "completed_at_monotonic_ms": telemetry.completed_at_monotonic_ms,
    }


def _filter_activity_generation_context(
    activity_generation_context: Optional[Dict[str, Any]],
) -> Dict[str, str | int]:
    if not activity_generation_context:
        return {}
    return {
        key: value
        for key, value in activity_generation_context.items()
        if key in _ACTIVITY_GENERATION_CONTEXT_KEYS
        and isinstance(value, (str, int))
    }


def _log_activity_local_generation_completed(
    logger: logging.Logger,
    *,
    generation_context: Dict[str, str | int],
    generation_telemetry: Optional[Dict[str, Any]],
    parse_outcome: str,
    error_category: Optional[str] = None,
) -> None:
    if not generation_context:
        return
    fields = {
        **generation_context,
        "parse_outcome": parse_outcome,
        "error_category": error_category,
    }
    if generation_telemetry:
        fields.update(generation_telemetry)
    logger.info(
        "activity_local_generation_completed %s",
        " ".join(f"{key}={value}" for key, value in fields.items() if value is not None),
    )


class ImageProcessor:
    def __init__(
        self,
        model_service: ModelService,
        storage_service: Optional[StorageService] = None,
        development_mode: bool = True,
        settings: Optional[Settings] = None,
        model_usage_service: Optional[ModelUsageService] = None
    ) -> None:
        """Initialize image processor service.
        
        Args:
            model_service: Service for managing AI models
            storage_service: Optional storage service for managing files
            development_mode: If True, uses development paths
            settings: Optional settings instance for configuration
            model_usage_service: Optional model usage service for model selection
        """
        self.model_service = model_service
        self.storage = storage_service or StorageService(development_mode)
        self.settings = settings or get_settings()
        
        # Store the model usage service or create one if not provided
        self.model_usage_service = model_usage_service or ModelUsageService(model_service)
        
        # Configure logging
        self.logger = api_logger.getChild("image_processor")
        
        # Initialize paths to None or default system path initially
        self.tesseract_cmd_path_to_use: Optional[str] = None
        self.tessdata_prefix_to_use: Optional[str] = None

        self._configure_tesseract_path()

    def _configure_tesseract_path(self) -> None:
        """Configure the tesseract binary path and TESSDATA_PREFIX for bundled applications."""
        try:
            is_bundled = os.getenv('BASIL_BUNDLED', 'false').lower() == 'true'
            
            tesseract_binary_path_to_set = None
            tessdata_prefix_path_to_set = None

            if is_bundled:
                self.logger.info("📦 Running in bundled mode. Configuring Tesseract paths for ImageProcessor...")
                current_file = Path(__file__).resolve()
                backend_root = current_file.parent.parent.parent.parent.parent # Adjust as per your structure

                self.logger.info(f"🔍 DEBUG (ImageProcessor): Current file path: {current_file}")
                self.logger.info(f"🔍 DEBUG (ImageProcessor): Calculated backend_root: {backend_root}")

                tesseract_bin_path = backend_root / "bin" / "tesseract"
                self.logger.info(f"🔍 Attempting tesseract binary path (ImageProcessor): {tesseract_bin_path}")

                if tesseract_bin_path.exists():
                    tesseract_binary_path_to_set = str(tesseract_bin_path)
                    self.logger.info(f"✅ Found tesseract binary at (ImageProcessor): {tesseract_bin_path}")
                    
                    tessdata_path = backend_root / "share" / "tessdata"
                    self.logger.info(f"🔍 Attempting tessdata path (ImageProcessor): {tessdata_path}")
                    
                    if tessdata_path.exists() and tessdata_path.is_dir():
                        tessdata_prefix_path_to_set = str(tessdata_path)
                        self.logger.info(f"✅ Found tessdata directory at (ImageProcessor): {tessdata_path}")
                    else:
                        self.logger.warning(f"⚠️ Bundled tessdata directory NOT FOUND at (ImageProcessor): {tessdata_path}")
                        alt_tessdata_path = tesseract_bin_path.parent.parent / "share" / "tessdata"
                        self.logger.info(f"🔍 Attempting alternative tessdata path (ImageProcessor): {alt_tessdata_path}")
                        if alt_tessdata_path.exists() and alt_tessdata_path.is_dir():
                            tessdata_prefix_path_to_set = str(alt_tessdata_path)
                            self.logger.info(f"✅ Found tessdata directory (alternative ImageProcessor): {alt_tessdata_path}")
                        else:
                            self.logger.warning(f"⚠️ Bundled tessdata directory NOT FOUND at alternative path (ImageProcessor): {alt_tessdata_path}")
                else:
                    self.logger.warning(f"⚠️ Bundled tesseract binary NOT FOUND at (ImageProcessor): {tesseract_bin_path}")

                if tesseract_binary_path_to_set:
                    pytesseract.pytesseract.tesseract_cmd = tesseract_binary_path_to_set
                    self.tesseract_cmd_path_to_use = tesseract_binary_path_to_set # Store for subprocess
                    self.logger.info(f"🔧 Set pytesseract.tesseract_cmd (ImageProcessor) to: {tesseract_binary_path_to_set}")
                else:
                    self.logger.warning("⚠️ Could not find bundled tesseract binary (ImageProcessor). Falling back to system tesseract.")
                    system_tesseract = shutil.which("tesseract")
                    if system_tesseract:
                        self.tesseract_cmd_path_to_use = system_tesseract
                        self.logger.info(f"🔧 Using system tesseract for subprocess (ImageProcessor): {system_tesseract}")
                    else:
                        self.logger.error("🆘 System tesseract not found in PATH either (ImageProcessor). Subprocess calls will likely fail.")
                
                if tessdata_prefix_path_to_set:
                    os.environ['TESSDATA_PREFIX'] = tessdata_prefix_path_to_set
                    self.tessdata_prefix_to_use = tessdata_prefix_path_to_set # Store for subprocess
                    self.logger.info(f"🔧 Set TESSDATA_PREFIX (ImageProcessor) to: {tessdata_prefix_path_to_set}")
                else:
                    self.logger.warning("⚠️ Could not find bundled tessdata directory (ImageProcessor).")
                    existing_tessdata = os.getenv('TESSDATA_PREFIX')
                    if existing_tessdata:
                        self.tessdata_prefix_to_use = existing_tessdata
                        self.logger.info(f"ℹ️ Using existing TESSDATA_PREFIX (ImageProcessor): {existing_tessdata}")
                    else:
                        self.logger.info("ℹ️ No TESSDATA_PREFIX is set and bundled one not found (ImageProcessor).")

            else:
                self.logger.info("💻 Running in development mode (ImageProcessor). Using system Tesseract.")
                system_tesseract = shutil.which("tesseract")
                if system_tesseract:
                    pytesseract.pytesseract.tesseract_cmd = system_tesseract
                    self.tesseract_cmd_path_to_use = system_tesseract
                    self.logger.info(f"🔧 Set pytesseract.tesseract_cmd (dev ImageProcessor) to: {system_tesseract}")
                else:
                    self.logger.error("🆘 System tesseract not found in PATH for development mode (ImageProcessor).")

                existing_tessdata = os.getenv('TESSDATA_PREFIX')
                if existing_tessdata:
                    self.tessdata_prefix_to_use = existing_tessdata
                    self.logger.info(f"ℹ️ System TESSDATA_PREFIX (ImageProcessor): {existing_tessdata}")
                else:
                    self.logger.info("ℹ️ No TESSDATA_PREFIX set for system Tesseract (ImageProcessor).")
                    
        except Exception as e:
            self.logger.error(f"❌ Error configuring tesseract paths (ImageProcessor): {e}", exc_info=True)

    async def _get_model_for_task(self, capabilities: Set[ModelCapability] | list[ModelCapability], model_id: Optional[str] = None) -> Optional[BaseAIModel]:
        """Get model for requested capabilities.
        
        Args:
            capabilities: Set or list of required model capabilities
            model_id: Optional specific model ID to use
            
        Returns:
            Model instance if available
        """
        # Simply delegate to the ModelUsageService for consistent model selection
        return await self.model_usage_service.get_model_for_task(
            capabilities=capabilities,
            explicit_model_id=model_id
        )

    def _clean_terminal_text(self, text: str) -> str:
        """Enhanced cleanup of terminal text output with special handling for logs and errors."""
        # Split into lines and normalize whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        
        # Remove ANSI escape sequences and process lines
        cleaned_lines = []
        in_traceback = False
        current_traceback = []
        
        for line in lines:
            # Remove ANSI escape sequences
            line = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", line)
            
            # Skip common terminal artifacts
            if re.match(r"^(\$|>|%|#)\s*$", line):
                continue
                
            # Handle log lines
            log_match = re.match(
                r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*-\s*(\w+)\s*-\s*(.*)$',
                line
            )
            if log_match:
                level, message = log_match.groups()
                # Keep ERROR and WARNING levels
                if level in ('ERROR', 'WARNING'):
                    cleaned_lines.append(f"{level}: {message}")
                else:
                    cleaned_lines.append(message)
                continue
                
            # Handle stack traces
            if 'Traceback (most recent call last)' in line:
                in_traceback = True
                current_traceback = [line]
                continue
                
            if in_traceback:
                current_traceback.append(line)
                # Check if we've reached the end of the traceback
                if re.match(r'^[A-Za-z]+Error:', line):
                    cleaned_lines.append(' '.join(current_traceback))
                    in_traceback = False
                    current_traceback = []
                continue
                
            if line.strip():
                cleaned_lines.append(line)

        # Join lines with space and normalize whitespace
        cleaned_text = ' '.join(cleaned_lines)
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        return cleaned_text

    def _sanitize_code_content(self, text: str) -> str:
        """Enhanced sanitization for code content and template variables."""
        # First handle malformed template variables and OCR artifacts
        processed_text = text
        
        # Replace common OCR misreadings of template variables
        ocr_fixes = {
            '{t': '[TEMPLATE_VAR]',
            '{I': '[TEMPLATE_VAR]',
            '{!t': '[TEMPLATE_VAR]',
            '{!I': '[TEMPLATE_VAR]',
            '°{': '[TEMPLATE_VAR]',
            '«': '',
            '»': '',
            '\u2018': "'",  # Smart quotes
            '\u2019': "'",
            '\u201C': '"',
            '\u201D': '"'
        }
        for bad, good in ocr_fixes.items():
            processed_text = processed_text.replace(bad, good)
            
        # Handle template patterns
        template_patterns = [
            r'\{![A-Za-z0-9._]+\}',         # Salesforce-style merge fields
            r'\{[A-Za-z0-9._]+\}',          # General template variables
            r'\{[!$]?[A-Za-z0-9._]+\}',     # Custom template syntax
            r'\{[^}]*\}'                     # Any remaining curly brace patterns
        ]
        
        for pattern in template_patterns:
            processed_text = re.sub(pattern, '[TEMPLATE_VAR]', processed_text)
            
        # Escape special characters for string formatting
        processed_text = processed_text.replace('{', '{{').replace('}', '}}')
        processed_text = processed_text.replace('%', '%%')
        
        # Preserve file paths while escaping special chars
        def preserve_path(match):
            path = match.group(0)
            return path.replace('{', '{{').replace('}', '}}')
        
        processed_text = re.sub(r'(?:/[\w.-]+)+/?', preserve_path, processed_text)
        processed_text = re.sub(r'(?:[A-Za-z]:\\[\w\\.-]+)', preserve_path, processed_text)
        
        return processed_text

    def _extract_json_from_response(self, response: str) -> Optional[str]:
        """Extract JSON from a response that may contain markdown code blocks or extra text.
        
        Note: As of the llama.cpp chat completion fix, local models now output clean JSON
        with <think> blocks already stripped. This method primarily handles edge cases and
        markdown-wrapped responses.
        
        Args:
            response: Raw model response that may contain JSON wrapped in markdown
            
        Returns:
            Extracted JSON string, or None if no valid JSON found
        """
        # Strategy 1: Look for JSON within markdown code blocks (```json ... ```)
        json_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        matches = re.findall(json_block_pattern, response)
        if matches:
            return matches[0].strip()
        
        # Strategy 2: Look for the first { to last } sequence (greedy JSON extraction)
        first_brace = response.find('{')
        last_brace = response.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = response[first_brace:last_brace + 1].strip()
            # Verify it at least looks like our expected structure
            if '"activity_type"' in potential_json:
                return potential_json
        
        return None
    
    def _parse_activity_analysis(self, response: str) -> ActivityAnalysis:
        """Parse a JSON-formatted response into an ActivityAnalysis object.
        
        Handles various response formats including:
        - Clean JSON
        - JSON wrapped in markdown code blocks
        - JSON mixed with explanatory text (e.g., from Qwen models)
        
        Args:
            response: JSON-formatted string with activity analysis (may include extra text)
            
        Returns:
            ActivityAnalysis object with parsed data
        """
        result = ActivityAnalysis()
        import json
        
        # Try to parse the response directly first
        try:
            parsed_json = json.loads(response)
            self.logger.debug("Successfully parsed JSON directly")
        except json.JSONDecodeError as e:
            # If direct parsing fails, try to extract JSON from the response
            self.logger.debug(f"Direct JSON parse failed: {e}, attempting extraction...")
            extracted_json = self._extract_json_from_response(response)
            
            if extracted_json:
                try:
                    parsed_json = json.loads(extracted_json)
                    self.logger.info("Successfully extracted and parsed JSON from response")
                except json.JSONDecodeError as e2:
                    self.logger.warning(f"Failed to parse extracted JSON: {e2}")
                    raise AnalysisError(
                        f"Failed to parse activity analysis JSON: {e2}"
                    ) from e2
            else:
                self.logger.warning("Could not extract valid JSON from response")
                raise AnalysisError(
                    "Model response contained no parseable activity analysis JSON"
                )
        
        # Map the JSON fields to ActivityAnalysis fields
        try:
            if "activity_type" in parsed_json:
                result.activity_type = parsed_json["activity_type"]
            if "context" in parsed_json:
                result.context = parsed_json["context"]
            if "content_summary" in parsed_json:
                result.content_summary = parsed_json["content_summary"]
            if "entities" in parsed_json and isinstance(parsed_json["entities"], list):
                result.entities = parsed_json["entities"]
            if "skills" in parsed_json and isinstance(parsed_json["skills"], list):
                result.skills = parsed_json["skills"]
            if "topics" in parsed_json and isinstance(parsed_json["topics"], list):
                result.topics = parsed_json["topics"]
            if "sentiment" in parsed_json:
                result.sentiment = parsed_json["sentiment"]
            if "complexity" in parsed_json:
                result.complexity = parsed_json["complexity"]
        except Exception as e:
            self.logger.warning(f"Error mapping JSON fields to ActivityAnalysis: {e}")
            # Set fallback values for unmapped fields
            if not result.activity_type:
                result.activity_type = "unknown"
            if not result.context:
                result.context = "Partial analysis available"
            if not result.content_summary:
                result.content_summary = "Activity detected but details incomplete"
            
        return result

    def extract_text(self, image_path: str) -> str:
        """Extract text from image using OCR with enhanced cleaning"""
        start_time = time.time()
        try:
            image = Image.open(image_path)
            text = pytesseract.image_to_string(image)
            cleaned = self._clean_terminal_text(text)
            result = self._sanitize_code_content(cleaned)
            self.logger.info(f"OCR processing took {time.time() - start_time:.2f} seconds")
            return result
        except Exception as e:
            error_time = time.time() - start_time
            self.logger.error(
                "OCR failed after %.2f seconds in ImageProcessor (%s)",
                error_time,
                type(e).__name__,
            )

            # Attempt direct subprocess call for more detailed error info
            try:
                tesseract_cmd_path = str(self.tesseract_cmd_path_to_use) if self.tesseract_cmd_path_to_use else "tesseract"
                tessdata_prefix_path = str(self.tessdata_prefix_to_use) if self.tessdata_prefix_to_use else os.getenv('TESSDATA_PREFIX', "")

                self.logger.info(f"Attempting direct Tesseract call (ImageProcessor) with instruction: {tesseract_cmd_path} --version")
                self.logger.info(f"Using TESSDATA_PREFIX for subprocess (ImageProcessor): {tessdata_prefix_path}")

                sub_env = os.environ.copy()
                if tessdata_prefix_path:
                    sub_env["TESSDATA_PREFIX"] = tessdata_prefix_path
                else:
                    if "TESSDATA_PREFIX" in sub_env:
                        del sub_env["TESSDATA_PREFIX"]

                process = subprocess.run(
                    [tesseract_cmd_path, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=sub_env,
                    timeout=15
                )
                self.logger.info(f"Direct Tesseract call stdout (ImageProcessor --version):\n{process.stdout}")
                if process.stderr:
                    self.logger.error(f"Direct Tesseract call stderr (ImageProcessor --version):\n{process.stderr}")
                else:
                    self.logger.info("Direct Tesseract call stderr (ImageProcessor --version): <empty>")
                self.logger.error(f"Direct Tesseract call return code (ImageProcessor --version): {process.returncode}")

            except subprocess.TimeoutExpired:
                self.logger.error("Direct Tesseract call (ImageProcessor --version) timed out.")
            except Exception as sub_e:
                self.logger.error(f"Error during direct Tesseract call (ImageProcessor --version): {str(sub_e)}")
            
            self.logger.error("OCR failed in ImageProcessor.extract_text (%s)", type(e).__name__)
            raise OCRError("OCR failed")

    async def analyze_text_only(
        self,
        extracted_text: str,
        app_name: str,
        custom_prompt: Optional[str] = None,
        pre_loaded_model: Optional[BaseAIModel] = None,
        model_id: Optional[str] = None,
        activity_generation_context: Optional[Dict[str, str | int]] = None,
    ) -> Dict[str, Any]:
        """Analyze content and generate activity analysis without image data.
        
        Args:
            extracted_text: The text to analyze
            app_name: Name of the application
            custom_prompt: Optional custom prompt to override default
            pre_loaded_model: Optional pre-loaded model to use instead of loading a new one
            model_id: Optional specific model ID to use for analysis
            activity_generation_context: Optional run/activity correlation fields for telemetry
        """
        start_time = time.time()
        generation_context = _filter_activity_generation_context(activity_generation_context)
        generation_telemetry: Optional[Dict[str, Any]] = None
        parse_outcome = "success"
        try:
            # Pre-process text
            cleaned_text = self._clean_terminal_text(extracted_text)
            processed_text = self._sanitize_code_content(cleaned_text)
            
            # Use pre-loaded model if provided, otherwise load a model with reasoning capabilities
            model = pre_loaded_model
            if model is None:
                self.logger.info("No pre-loaded model provided, loading a reasoning model")
                model = await self._get_model_for_task({ModelCapability.REASONING}, model_id=model_id)
            
            if not model:
                self.logger.warning("No suitable model found for text analysis")
                _log_activity_local_generation_completed(
                    self.logger,
                    generation_context=generation_context,
                    generation_telemetry=None,
                    parse_outcome="no_model",
                    error_category="no_model",
                )
                return {
                    "analysis": ActivityAnalysis(
                        context="No reasoning model available",
                        content_summary="Unable to analyze text - no suitable model found",
                        activity_type="unknown"
                    ),
                    "extracted_text": extracted_text,
                    "analysis_type": "none",
                    "parse_outcome": "no_model",
                }
            
            analysis_max_tokens = resolve_activity_analysis_output_tokens(model)
            generation_context = {
                **generation_context,
                "analysis_requested_tokens": analysis_max_tokens,
            }

            if custom_prompt:
                try:
                    # Try with initial cleaning
                    prompt = custom_prompt.format(
                        app_name=app_name,
                        extracted_text=processed_text
                    )
                except (KeyError, ValueError) as e:
                    self.logger.warning(f"Initial prompt formatting failed: {e}, trying with aggressive cleaning")
                    try:
                        # Try with more aggressive cleaning
                        processed_text = re.sub(r'\{\{.*?\}\}|\{.*?\}', '[TEMPLATE_VAR]', processed_text)
                        processed_text = processed_text.replace('{', '{{').replace('}', '}}')
                        processed_text = processed_text.replace('%', '%%')
                        prompt = custom_prompt.format(
                            app_name=app_name,
                            extracted_text=processed_text
                        )
                    except (KeyError, ValueError) as e:
                        self.logger.warning(f"Second attempt failed: {e}, removing all special characters")
                        processed_text = re.sub(r'[^a-zA-Z0-9\s.,;:\-_()]', ' ', processed_text)
                        prompt = custom_prompt.format(
                            app_name=app_name,
                            extracted_text=processed_text
                        )
            else:
                prompt = """You are an AI assistant that analyzes user activities to build a comprehensive profile of their work and interests.
Analyze the content and provide a detailed understanding of what the user is doing.

Current Application: {app_name}
Content:
{extracted_text}

Based on this content, provide a detailed analysis in JSON format with the following structure:

{{
  "activity_type": "The type of activity (coding, writing, browsing, communicating, etc.)",
  "context": "A brief description of what the user is doing",
  "content_summary": "A summary of the content visible in the window",
  "entities": [
    {{
      "type": "person/project/technology/topic/etc.",
      "name": "Name of the entity",
      "confidence": 0.0-1.0
    }}
  ],
  "skills": ["List of skills being used or demonstrated"],
  "topics": ["List of topics being discussed or worked on"],
  "sentiment": "The user's apparent sentiment or focus state (optional)",
  "complexity": "Assessment of the complexity of the task (optional)"
}}

IMPORTANT GUIDELINES:
1. Focus on understanding what the user is doing, not suggesting what they should do next
2. Be comprehensive but concise in your analysis
3. Extract meaningful entities, skills, and topics that help build a profile of the user's work
4. Do not include any instructions or explanations outside the JSON structure
5. If you can't determine certain fields, use reasonable defaults or omit optional fields
6. Return valid JSON that can be parsed programmatically
7. Do NOT use markdown code blocks, backticks, or any markdown formatting - return raw JSON only""".format(
                    app_name=app_name,
                    extracted_text=processed_text
                )

            # Log the prompt length to help diagnose performance issues
            self.logger.debug(f"Prompt length for text-only analysis: {len(prompt)} characters")

            def _capture_generation_telemetry(telemetry: LocalCompletionTelemetry) -> None:
                nonlocal generation_telemetry
                generation_telemetry = _telemetry_to_dict(telemetry)
            
            # Generate response using the already loaded model
            # Search must stay off: a cloud processing model would otherwise
            # research the screen text and return prose-wrapped results that
            # cannot parse as the JSON body this analysis requires.
            raw_result = await call_model_with_prompt(
                model,
                prompt=prompt,
                max_tokens=analysis_max_tokens,
                purpose="activity_analysis",
                enable_web_search=False,
                on_local_generation_telemetry=_capture_generation_telemetry,
            )
            
            # Parse the JSON response into an ActivityAnalysis object
            try:
                parsed_result = self._parse_activity_analysis(raw_result)
            except AnalysisError:
                parse_outcome = "error"
                raise
            
            self.logger.info(f"Analysis completed in {time.time() - start_time:.2f} seconds")
            result: Dict[str, Any] = {
                "analysis": parsed_result,
                "extracted_text": extracted_text,
                "analysis_type": "text-only",
                "processing_time_ms": int((time.time() - start_time) * 1000),
                "parse_outcome": parse_outcome,
            }
            if generation_telemetry is not None:
                result["generation_telemetry"] = generation_telemetry
            _log_activity_local_generation_completed(
                self.logger,
                generation_context=generation_context,
                generation_telemetry=generation_telemetry,
                parse_outcome=parse_outcome,
            )
            return result

        except AnalysisError as e:
            self.logger.error("Activity analysis failed (%s)", type(e).__name__)
            _log_activity_local_generation_completed(
                self.logger,
                generation_context=generation_context,
                generation_telemetry=generation_telemetry,
                parse_outcome="error",
                error_category="parse",
            )
            return {
                "analysis": ActivityAnalysis(
                    context="Error during analysis",
                    content_summary="Unable to complete analysis due to an error",
                    activity_type="error"
                ),
                "extracted_text": extracted_text,
                "analysis_type": "error",
                "error": str(e),
                "parse_outcome": "error",
                "generation_telemetry": generation_telemetry,
            }
        except Exception as e:
            self.logger.error("Activity analysis failed (%s)", type(e).__name__)
            _log_activity_local_generation_completed(
                self.logger,
                generation_context=generation_context,
                generation_telemetry=generation_telemetry,
                parse_outcome="error",
                error_category="generation",
            )
            return {
                "analysis": ActivityAnalysis(
                    context="Error during analysis",
                    content_summary="Unable to complete analysis due to an error",
                    activity_type="error"
                ),
                "extracted_text": extracted_text,
                "analysis_type": "error",
                "error": str(e),
                "parse_outcome": "error",
                "generation_telemetry": generation_telemetry,
            }

    async def process_image(
        self,
        image_path: str,
        force_text_only: bool = False,
        model_id: Optional[str] = None,
        model_stage_semaphore: Optional[asyncio.Semaphore] = None,
        diagnostic_context: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResponse:
        """Process an image using OCR and AI analysis.
        
        Args:
            image_path: Path to the image file
            force_text_only: If True, only perform text-based analysis regardless of image content
            model_id: Optional specific model ID to use for processing
            
        Returns:
            ProcessingResponse with extracted text and analysis result
        """
        image_id = f"img_{int(time.time() * 1000)}"
        total_start = time.perf_counter()
        sanitized_diagnostic_context = {
            key: value
            for key, value in (diagnostic_context or {}).items()
            if key in {
                "run_id",
                "activity_id",
                "analysis_model_id",
                "analysis_requested_tokens",
            }
        }
        if diagnostic_context is None:
            diagnostic_context = sanitized_diagnostic_context
        else:
            diagnostic_context.clear()
            diagnostic_context.update(sanitized_diagnostic_context)
        stage = "image_processing"

        def _log_stage(stage: str, duration_ms: int = 0, *, outcome: str = "started", **metadata: Any) -> None:
            fields = {
                **diagnostic_context,
                "stage": stage,
                "outcome": outcome,
                "duration_ms": duration_ms,
                **metadata,
            }
            safe_fields = {
                key: value
                for key, value in fields.items()
                if key
                in {
                    "run_id",
                    "activity_id",
                    "analysis_model_id",
                    "analysis_requested_tokens",
                    "stage",
                    "outcome",
                    "duration_ms",
                    "model_id",
                    "text_chars",
                    "model_handler",
                    "analysis_output_chars",
                    "exception_type",
                }
                and (isinstance(value, (str, int, float, bool)) or value is None)
            }
            self.logger.info(
                "activity_image_processing_stage %s",
                " ".join(f"{key}={value}" for key, value in safe_fields.items()),
            )

        _log_stage("image_processing", model_id=model_id or "default")

        # Extract app name from file path if available
        app_name = Path(image_path).stem.split("_")[-1] if "_" in Path(image_path).stem else "Unknown"
        try:
            # Extract text with OCR
            stage = "ocr"
            _log_stage("ocr")
            ocr_start = time.perf_counter()
            extracted_text = await asyncio.to_thread(self.extract_text, image_path)
            _log_stage(
                "ocr",
                int((time.perf_counter() - ocr_start) * 1000),
                outcome="completed",
                text_chars=len(extracted_text),
            )

            async def _analyze_with_model() -> Optional[Dict[str, Any]]:
                nonlocal stage
                stage = "model_acquisition"
                _log_stage("model_acquisition")
                model_start = time.perf_counter()
                reasoning_model = await self._get_model_for_task(
                    {ModelCapability.REASONING},
                    model_id=model_id,
                )
                _log_stage(
                    "model_acquisition",
                    int((time.perf_counter() - model_start) * 1000),
                    outcome="completed",
                    model_handler=getattr(
                        getattr(reasoning_model, "handler", None),
                        "value",
                        getattr(reasoning_model, "handler", None),
                    ),
                )
                if not reasoning_model:
                    return None

                analysis_max_tokens = resolve_activity_analysis_output_tokens(reasoning_model)
                if diagnostic_context is not None:
                    diagnostic_context["analysis_requested_tokens"] = analysis_max_tokens

                stage = "analysis"
                _log_stage("analysis", analysis_requested_tokens=analysis_max_tokens)
                analysis_start = time.perf_counter()
                result = await self.analyze_text_only(
                    extracted_text,
                    app_name,
                    pre_loaded_model=reasoning_model,
                    model_id=model_id,
                    activity_generation_context=diagnostic_context,
                )
                if diagnostic_context is not None and result.get("generation_telemetry") is not None:
                    diagnostic_context["generation_telemetry"] = result["generation_telemetry"]
                if diagnostic_context is not None:
                    diagnostic_context["parse_outcome"] = result.get(
                        "parse_outcome",
                        "success",
                    )
                _log_stage(
                    "analysis",
                    int((time.perf_counter() - analysis_start) * 1000),
                    outcome="completed",
                    analysis_requested_tokens=analysis_max_tokens,
                    analysis_output_chars=len(str(result.get("analysis") or "")),
                )
                return result

            if model_stage_semaphore is None:
                result = await _analyze_with_model()
            else:
                async with model_stage_semaphore:
                    result = await _analyze_with_model()

            if result is None:
                _log_stage(
                    "image_processing",
                    int((time.perf_counter() - total_start) * 1000),
                    outcome="no_model",
                )
                return ProcessingResponse(
                    extracted_text=extracted_text,
                    analysis=ActivityAnalysis(
                        context="No reasoning model available",
                        content_summary="Unable to analyze text - no suitable model found",
                        activity_type="unknown",
                    ),
                    analysis_type="none",
                    processing_time_ms=int((time.perf_counter() - total_start) * 1000),
                )

            processing_time_ms = result.get(
                "processing_time_ms",
                int((time.perf_counter() - total_start) * 1000),
            )
            _log_stage(
                "image_processing",
                int((time.perf_counter() - total_start) * 1000),
                outcome="completed",
            )
            
            return ProcessingResponse(
                extracted_text=extracted_text,
                analysis=result["analysis"],
                analysis_type=result.get("analysis_type", "text-only"),
                processing_time_ms=processing_time_ms,
                error=result.get("error")
            )
        except Exception as e:
            _log_stage(
                stage,
                int((time.perf_counter() - total_start) * 1000),
                outcome="failed",
                exception_type=type(e).__name__,
            )
            _log_stage(
                "image_processing",
                int((time.perf_counter() - total_start) * 1000),
                outcome="failed",
                exception_type=type(e).__name__,
            )
            self.logger.error(
                "[%s] Image processing failed (%s)",
                image_id,
                type(e).__name__,
            )
            return ProcessingResponse(
                extracted_text="Error during processing",
                analysis=ActivityAnalysis(
                    context="Error during processing",
                    content_summary="Unable to process image",
                    activity_type="error"
                ),
                analysis_type="error",
                processing_time_ms=int((time.perf_counter() - total_start) * 1000),
                error=str(e)
            )