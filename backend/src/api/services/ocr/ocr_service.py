"""OCR text extraction service for processing images into text."""

import pytesseract  # type: ignore[import-untyped]
from PIL import Image
import re
import time
import logging
import os
import shutil
import subprocess
from typing import Dict, Any, Optional
from pathlib import Path

from ...core.config.api_settings import Settings
from ...core.logging.api_logger import api_logger
from ...core.services.file_storage_service import StorageService
from .ocr_models import OCRResult, OCRError

logger = logging.getLogger(__name__)

class OCRService:
    """Service that extracts text from images using OCR technology."""
    
    def __init__(self, settings: Optional[Settings] = None, storage_service: Optional[StorageService] = None, development_mode: bool = False):
        """Initialize OCR service."""
        self.settings = settings if settings else Settings()
        self.storage_service = storage_service if storage_service else StorageService(development_mode=development_mode)
        self.logger = api_logger.getChild("ocr_service")
        
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
                self.logger.info("📦 Running in bundled mode. Configuring Tesseract paths for OCRService...")
                current_file = Path(__file__).resolve()
                # Path example: .../Basil.app/Contents/Resources/backend/src/api/services/ocr/ocr_service.py
                # Adjust depth according to actual structure if this is different for ocr_service
                backend_root = current_file.parent.parent.parent.parent.parent 

                self.logger.info(f"🔍 DEBUG (OCRService): Current file path: {current_file}")
                self.logger.info(f"🔍 DEBUG (OCRService): Calculated backend_root: {backend_root}")

                tesseract_bin_path = backend_root / "bin" / "tesseract"
                self.logger.info(f"🔍 Attempting tesseract binary path (OCRService): {tesseract_bin_path}")

                if tesseract_bin_path.exists():
                    tesseract_binary_path_to_set = str(tesseract_bin_path)
                    self.logger.info(f"✅ Found tesseract binary at (OCRService): {tesseract_bin_path}")
                    
                    tessdata_path = backend_root / "share" / "tessdata"
                    self.logger.info(f"🔍 Attempting tessdata path (OCRService): {tessdata_path}")
                    
                    if tessdata_path.exists() and tessdata_path.is_dir():
                        tessdata_prefix_path_to_set = str(tessdata_path)
                        self.logger.info(f"✅ Found tessdata directory at (OCRService): {tessdata_path}")
                    else:
                        self.logger.warning(f"⚠️ Bundled tessdata directory NOT FOUND at (OCRService): {tessdata_path}")
                        alt_tessdata_path = tesseract_bin_path.parent.parent / "share" / "tessdata"
                        self.logger.info(f"🔍 Attempting alternative tessdata path (OCRService): {alt_tessdata_path}")
                        if alt_tessdata_path.exists() and alt_tessdata_path.is_dir():
                            tessdata_prefix_path_to_set = str(alt_tessdata_path)
                            self.logger.info(f"✅ Found tessdata directory (alternative OCRService): {alt_tessdata_path}")
                        else:
                            self.logger.warning(f"⚠️ Bundled tessdata directory NOT FOUND at alternative path (OCRService): {alt_tessdata_path}")
                else:
                    self.logger.warning(f"⚠️ Bundled tesseract binary NOT FOUND at (OCRService): {tesseract_bin_path}")

                if tesseract_binary_path_to_set:
                    pytesseract.pytesseract.tesseract_cmd = tesseract_binary_path_to_set
                    self.tesseract_cmd_path_to_use = tesseract_binary_path_to_set # Store for subprocess
                    self.logger.info(f"🔧 Set pytesseract.tesseract_cmd (OCRService) to: {tesseract_binary_path_to_set}")
                else:
                    self.logger.warning("⚠️ Could not find bundled tesseract binary (OCRService). Falling back to system tesseract.")
                    system_tesseract = shutil.which("tesseract")
                    if system_tesseract:
                        self.tesseract_cmd_path_to_use = system_tesseract
                        self.logger.info(f"🔧 Using system tesseract for subprocess (OCRService): {system_tesseract}")
                    else:
                        self.logger.error("🆘 System tesseract not found in PATH either (OCRService). Subprocess calls will likely fail.")
                
                if tessdata_prefix_path_to_set:
                    os.environ['TESSDATA_PREFIX'] = tessdata_prefix_path_to_set
                    self.tessdata_prefix_to_use = tessdata_prefix_path_to_set # Store for subprocess
                    self.logger.info(f"🔧 Set TESSDATA_PREFIX (OCRService) to: {tessdata_prefix_path_to_set}")
                else:
                    self.logger.warning("⚠️ Could not find bundled tessdata directory (OCRService).")
                    existing_tessdata = os.getenv('TESSDATA_PREFIX')
                    if existing_tessdata:
                        self.tessdata_prefix_to_use = existing_tessdata
                        self.logger.info(f"ℹ️ Using existing TESSDATA_PREFIX (OCRService): {existing_tessdata}")
                    else:
                        self.logger.info("ℹ️ No TESSDATA_PREFIX is set and bundled one not found (OCRService).")

            else:
                self.logger.info("💻 Running in development mode (OCRService). Using system Tesseract.")
                system_tesseract = shutil.which("tesseract")
                if system_tesseract:
                    pytesseract.pytesseract.tesseract_cmd = system_tesseract
                    self.tesseract_cmd_path_to_use = system_tesseract
                    self.logger.info(f"🔧 Set pytesseract.tesseract_cmd (dev OCRService) to: {system_tesseract}")
                else:
                    self.logger.error("🆘 System tesseract not found in PATH for development mode (OCRService).")

                existing_tessdata = os.getenv('TESSDATA_PREFIX')
                if existing_tessdata:
                    self.tessdata_prefix_to_use = existing_tessdata
                    self.logger.info(f"ℹ️ System TESSDATA_PREFIX (OCRService): {existing_tessdata}")
                else:
                    self.logger.info("ℹ️ No TESSDATA_PREFIX set for system Tesseract (OCRService).")
                    
        except Exception as e:
            self.logger.error(f"❌ Error configuring tesseract paths (OCRService): {e}", exc_info=True)

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
    
    def _format_text_for_display(self, text: str) -> Dict[str, str]:
        """Format text to preserve newlines and structure for client display.
        
        This method takes raw OCR text and prepares it in multiple formats
        for easy consumption by different client types.
        
        Args:
            text: Raw OCR text with possibly escaped newlines
            
        Returns:
            Dictionary with formatted text and format type
        """
        if text is None or not text.strip():
            return {"formatted_text": "", "format_type": "plain"}
        
        # Log original text characteristics
        self.logger.info(f"Formatting text for display, original length: {len(text)}")
        original_newline_count = text.count('\n')
        original_escaped_newline_count = text.count('\\n')
        self.logger.info(f"Original text has {original_newline_count} actual newlines and {original_escaped_newline_count} escaped newlines")
        
        # Step 1: Process text to handle all types of newlines
        processed_text = text
        
        # Handle double-escaped newlines first (e.g., \\n)
        processed_text = processed_text.replace('\\\\n', '\n')
        
        # Handle regular escaped newlines
        processed_text = processed_text.replace('\\n', '\n')
        
        # Handle Windows-style line endings
        processed_text = processed_text.replace('\\r\\n', '\n')
        processed_text = processed_text.replace('\\r', '\n')
        
        # Step 2: Clean up whitespace while preserving line breaks
        # Split by lines, trim each line, then rejoin
        lines = [line.rstrip() for line in processed_text.split('\n')]
        processed_text = '\n'.join(lines)
        
        # Log resulting text characteristics
        resulting_newline_count = processed_text.count('\n')
        self.logger.info(f"After processing, text has {resulting_newline_count} newlines")
        
        # Step 3: Format as HTML for client display
        html_text = processed_text
        
        # Replace newlines with <br> tags
        html_text = html_text.replace('\n', '<br>\n')
        
        # Wrap in a div with proper styling for whitespace preservation
        html_text = f"""<div style="white-space: pre-wrap; font-family: monospace; line-height: 1.5;">
{html_text}
</div>"""
        
        return {
            "formatted_text": html_text,
            "format_type": "html"
        }

    def extract_text(self, image_path: str) -> OCRResult:
        """Extract text from image using OCR with enhanced cleaning and formatting.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            OCRResult object containing extracted text, processed text, and timing information
        """
        start_time = time.time()
        self.logger.info(f"Starting OCR text extraction for {image_path}")
        
        try:
            # Extract app name from file path if available
            app_name = Path(image_path).stem.split("_")[-1] if "_" in Path(image_path).stem else "Unknown"
            self.logger.info(f"Detected app_name: {app_name}")
            
            # Perform OCR on the image
            image = Image.open(image_path)
            raw_text = pytesseract.image_to_string(image)
            
            # Clean and process the text
            cleaned_text = self._clean_terminal_text(raw_text)
            processed_text = self._sanitize_code_content(cleaned_text)
            
            # Format text for display, preserving newlines
            formatted_result = self._format_text_for_display(raw_text)
            
            # Calculate processing time
            processing_time = time.time() - start_time
            self.logger.info(f"OCR processing completed in {processing_time:.2f} seconds")
            
            # Return the results as a structured OCRResult
            return OCRResult(
                status="success",
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                processed_text=processed_text,
                formatted_text=formatted_result["formatted_text"],
                format_type=formatted_result["format_type"],
                app_name=app_name,
                image_path=image_path,
                processing_time_ms=int(processing_time * 1000)
            )
            
        except Exception as e:
            error_time = time.time() - start_time
            self.logger.error(f"OCR failed after {error_time:.2f} seconds with pytesseract: {str(e)}")

            # Attempt direct subprocess call for more detailed error info
            try:
                tesseract_cmd_path = str(self.tesseract_cmd_path_to_use) if self.tesseract_cmd_path_to_use else "tesseract"
                tessdata_prefix_path = str(self.tessdata_prefix_to_use) if self.tessdata_prefix_to_use else os.getenv('TESSDATA_PREFIX', "")
                
                self.logger.info(f"Attempting direct Tesseract call (OCRService) with instruction: {tesseract_cmd_path} --version")
                self.logger.info(f"Using TESSDATA_PREFIX for subprocess (OCRService): {tessdata_prefix_path}")

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
                    check=False, # Don't raise exception on non-zero exit
                    env=sub_env,
                    timeout=15  # Slightly longer timeout for --version, just in case
                )
                self.logger.info(f"Direct Tesseract call stdout (OCRService --version):\n{process.stdout}")
                if process.stderr:
                    self.logger.error(f"Direct Tesseract call stderr (OCRService --version):\n{process.stderr}")
                else:
                    self.logger.info("Direct Tesseract call stderr (OCRService --version): <empty>")
                self.logger.error(f"Direct Tesseract call return code (OCRService --version): {process.returncode}")
                
            except subprocess.TimeoutExpired:
                self.logger.error("Direct Tesseract call (OCRService --version) timed out.")
            except Exception as sub_e:
                self.logger.error(f"Error during direct Tesseract call (OCRService --version): {str(sub_e)}")

            # Re-raise the original exception from pytesseract to maintain original error flow for now
            raise e
            
        return OCRResult(
            status="error",
            error=f"OCR failed: {str(e)}",
            error_type=type(e).__name__,
            image_path=image_path,
            processing_time_ms=int(error_time * 1000)
        ) 