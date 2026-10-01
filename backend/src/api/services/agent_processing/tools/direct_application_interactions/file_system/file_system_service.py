"""
File System Service - Main Interface for Agent Integration

Provides the primary interface for file system operations within the agent workflow.
Focuses on the core use case: "Take this document and draft a reply to this email"

This service coordinates between file retrieval, content processing, and LLM integration.
"""

import asyncio
import logging
import inspect
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

from api.core.security.protected_runtime_paths import (
    PROTECTED_RUNTIME_REFUSAL,
    is_protected_runtime_path,
    log_protected_runtime_refusal,
)
from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

from .text_file_write import LocalTextFileWriter
from .identification_retrieval import FileRetrievalService, CloudStorageService, FileContextDetectionService
from .identification_retrieval import file_find_orchestrator
from .file_models import (
    FileSearchCriteria, FileMetadata, FileContent, FileSearchResult,
    FileType, ContentEncoding, LLMFileRequest
)

logger = logging.getLogger(__name__)


class FileSystemService:
    """
    Main file system service for agent integration.
    
    Provides high-level file operations for agent_tasks and automation.
    Primary focus: Finding files by name and preparing them for LLM processing.
    """
    
    def __init__(self, write_roots: Optional[List[Path]] = None):
        self.retrieval_service = FileRetrievalService()
        self.cloud_service = CloudStorageService()
        self.context_detection_service = FileContextDetectionService() # NEW
        self._text_file_writer = LocalTextFileWriter(write_roots or [Path.home(), self._detect_backend_root()])
        
        # Default search paths for local files
        self.default_search_paths = [
            str(Path.home() / "Documents"),
            str(Path.home() / "Desktop"), 
            str(Path.home() / "Downloads"),
            "/Applications"
        ]
        self.cloud_search_paths = []
    
    async def write_text_file(
        self,
        path: str,
        content: str,
        mode: str,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write direct UTF-8 text without shell serialization or approval prompts.

        Routed through ManagedFileHistoryService so eligible paths (see
        managed_history/eligibility.py) get durable version history and
        rollback support. Ineligible paths, and any failure to construct the
        managed-history service itself, fall back to the plain writer so this
        never narrows existing agent write capability.
        """
        logger.info("Agent text-file write request path=%s mode=%s", path, mode)
        if is_protected_runtime_path(path):
            log_protected_runtime_refusal("file write")
            return {
                "success": False,
                "file_path": path,
                "operation": "create" if mode == "create" else "modify",
                "mode": mode,
                "error_type": "policy_blocked",
                "error": PROTECTED_RUNTIME_REFUSAL,
                "previous_sha256": None,
                "execution_success": False,
                "file_artifacts": [],
            }
        context = get_current_agent_context()
        root_task_id = context.get("root_task_id") or context.get("agent_task_id")
        agent_task_id = context.get("agent_task_id")
        if root_task_id and agent_task_id:
            try:
                from .managed_history.managed_file_history_wiring import get_managed_file_history_service

                service = get_managed_file_history_service(text_writer=self._text_file_writer)
            except Exception:
                logger.warning(
                    "Managed file history could not be constructed; falling back to the plain text writer.",
                    exc_info=True,
                )
            else:
                return await service.apply_managed_write(
                    root_task_id=str(root_task_id),
                    agent_task_id=str(agent_task_id),
                    path=path,
                    content=content,
                    mode=mode,
                    expected_sha256=expected_sha256,
                )
        return await self._text_file_writer.write_text_file(
            path=path,
            content=content,
            mode=mode,
            expected_sha256=expected_sha256,
        )

    @staticmethod
    def _detect_backend_root() -> Path:
        for parent in Path(__file__).resolve().parents:
            if (parent / "src").is_dir():
                return parent
        return Path(__file__).resolve().parent

    async def find_file_for_llm(self, filename: str, context: str = "", 
                               search_paths: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Find a file by name and prepare it for LLM processing.
        
        This is the primary method for agent workflows like:
        "Take this document and draft a reply to this email"
        
        Args:
            filename: Name or partial name of file to find
            context: Additional context for LLM processing
            search_paths: Optional specific paths to search (defaults to common document locations)
            
        Returns:
            Dictionary with file information ready for agent processing, or None if not found
        """
        logger.info(f"🎯 Agent request: Find file '{filename}' for LLM processing")

        try:
            # Use default search paths if none provided, include cloud storage.
            if search_paths is None:
                search_paths = self.default_search_paths + self.cloud_search_paths

            # Orchestrator runs Spotlight, falls back to cloud `find` when the
            # local result is empty/weak, ranks all candidates, and either
            # prepares a confident single match or returns a ranked candidate
            # list for the agent to disambiguate.
            return await file_find_orchestrator.find_or_list_candidates(
                self.retrieval_service,
                self.cloud_service,
                filename,
                context,
                search_paths,
            )

        except Exception as e:
            logger.error(f"❌ Error finding file for LLM: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "file_name": filename
            }

    async def prepare_file_by_path(self, path: str, context: str = "") -> Dict[str, Any]:
        """
        Prepare a specific file (by absolute path) for LLM processing.

        This is the follow-up to `find_file_for_llm` when it returns ranked
        candidates: the agent picks a candidate `path` and calls this to load the
        file's content.

        Args:
            path: Absolute path of the file to prepare
            context: Additional context for LLM processing

        Returns:
            Dict with file content prepared for LLM, or success=False on failure
        """
        logger.info(f"📎 Agent request: Prepare file by path '{path}'")
        try:
            return await file_find_orchestrator.prepare_path(
                self.retrieval_service, path, context
            )
        except Exception as e:
            logger.error(f"❌ Error preparing file by path: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "file_path": path
            }

    async def search_files(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search for files based on criteria.
        
        Args:
            criteria: Search criteria dictionary
            
        Returns:
            Search results in agent-friendly format
        """
        logger.info(f"🔍 Agent search request: {criteria}")
        
        try:
            search_paths = criteria.get('search_paths', self.default_search_paths)
            search_term = criteria.get('exact_name') or criteria.get('name_contains', '')
            
            search_result = await self.retrieval_service.search_files_by_name(
                search_term,
                search_paths
            )
            
            # Convert to agent-friendly format
            files = []
            for file_meta in search_result.files_found:
                files.append({
                    "name": file_meta.name,
                    "path": file_meta.path,
                    "size": file_meta.size,
                    "type": file_meta.file_type.value,
                    "extension": file_meta.extension,
                    "modified_date": file_meta.modified_date.isoformat(),
                    "parent_directory": file_meta.parent_directory
                })
            
            result = {
                "success": True,
                "total_found": len(files),
                "search_duration": search_result.search_duration,
                "search_method": search_result.search_method,
                "files": files
            }
            
            logger.info(f"✅ Search completed: {len(files)} files found")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error searching files: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "total_found": 0,
                "files": []
            }
    
    async def get_file_content(self, file_path: str, encoding: str = "base64") -> Dict[str, Any]:
        """
        Get content of a specific file.
        
        Args:
            file_path: Path to the file
            encoding: Encoding method ("utf8_text", "base64", "extracted_text")
            
        Returns:
            File content in agent-friendly format
        """
        logger.info(f"📖 Agent content request: {file_path} (encoding: {encoding})")
        
        try:
            # Convert encoding string to enum
            encoding_enum = ContentEncoding(encoding)
            
            # Read file content
            file_content = await self.retrieval_service.read_file_content(file_path, encoding_enum)
            
            if not file_content:
                return {
                    "success": False,
                    "error": "Could not read file content",
                    "file_path": file_path
                }
            
            result = {
                "success": True,
                "file_path": file_path,
                "content_type": file_content.content_type.value,
                "content_size": file_content.content_size,
                "extraction_method": file_content.extraction_method
            }
            
            # Include content based on encoding
            if file_content.content_type == ContentEncoding.UTF8_TEXT:
                result["text_content"] = file_content.raw_content
            elif file_content.content_type == ContentEncoding.BASE64:
                result["base64_content"] = file_content.base64_content
            elif file_content.content_type == ContentEncoding.EXTRACTED_TEXT:
                result["extracted_text"] = file_content.extracted_text
            
            # Include metadata if available
            if file_content.metadata:
                result["metadata"] = {
                    "name": file_content.metadata.name,
                    "size": file_content.metadata.size,
                    "type": file_content.metadata.file_type.value,
                    "extension": file_content.metadata.extension,
                    "modified_date": file_content.metadata.modified_date.isoformat()
                }
            
            logger.info(f"✅ Content retrieved: {result['content_size']} bytes")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error getting file content: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path
            }
    
    async def detect_and_prepare_current_document(self, context: str = "") -> Optional[Dict[str, Any]]:
        """
        Main workflow: Detect the current document and prepare it for LLM processing.
        
        This implements the "take this document and draft a reply" use case by:
        1. Detecting what file the user is currently viewing
        2. Retrieving and preparing the file content for LLM
        3. Returning comprehensive file information
        
        Args:
            context: Additional context for LLM processing
            
        Returns:
            Dict with file information and LLM-ready content, or None if detection fails
        """
        logger.info("🚀 Starting 'take this document' workflow...")
        if self._should_block_current_document_detection(context):
            reference_paths = get_current_agent_context().get("reference_paths") or []
            logger.warning(
                "Blocked current-document detection because explicit reference_paths are authoritative: %s",
                reference_paths,
            )
            return {
                "success": False,
                "error": (
                    "Current-document detection is not appropriate for this task because explicit "
                    "reference_paths were provided. Use those paths directly instead of probing the "
                    "frontmost window."
                ),
                "tool_selection_error": True,
                "reference_paths": reference_paths,
            }
        
        # Step 1: Detect current file context. Prefer snapshot hints from provided context if available
        app_name_hint = None
        bundle_id_hint = None
        window_title_hint = None
        try:
            if isinstance(context, dict):
                app_ctx = context.get("app_context") or {}
                app_name_hint = app_ctx.get("app_name") or context.get("active_app")
                bundle_id_hint = app_ctx.get("bundle_id")
                window_title_hint = app_ctx.get("window_title") or context.get("window_title")
        except Exception:
            pass

        # Fallback: pull snapshot from the agent-task submission service if hints are missing
        if not app_name_hint and not window_title_hint:
            try:
                from api.main import app  # late import to avoid cycles
                submission_service = getattr(app.state, "agent_task_submission_service", None)
                if submission_service and hasattr(submission_service, "get_current_screenshot_data"):
                    shot = submission_service.get_current_screenshot_data()
                    if shot and shot.get("success"):
                        app_name_hint = shot.get("app_name") or app_name_hint
                        window_title_hint = shot.get("window_title") or window_title_hint
            except Exception:
                # Non-fatal: proceed without snapshot hints
                pass

        context_result = await self.context_detection_service.detect_current_file_context(
            app_name_hint=app_name_hint,
            bundle_id_hint=bundle_id_hint,
            window_title_hint=window_title_hint,
        )
        
        if not context_result.success:
            logger.warning(f"❌ Could not detect current file: {context_result.error_message}")
            return {
                "success": False,
                "error": "Could not detect current file context",
                "detection_result": context_result,
                "suggestions": [
                    "Try opening a document file",
                    "Ensure the file has a clear filename in the window title",
                    "Use the file search method instead"
                ]
            }
        
        logger.info(f"✅ Detected file: {context_result.detected_filename}")
        
        # Step 2: Try to find and prepare the detected file
        if context_result.detected_path and Path(context_result.detected_path).is_absolute():
            # We have an absolute path, use it directly
            file_path = context_result.detected_path
            logger.info(f"📁 Using absolute path: {file_path}")
            
            try:
                llm_request = await self.retrieval_service.prepare_file_for_llm(
                    file_path, 
                    context,
                    ContentEncoding.BASE64  # Default to Base64 for LLM compatibility
                )
                
                if llm_request:
                    return {
                        "success": True,
                        "detection_method": context_result.detection_method,
                        "confidence": context_result.confidence,
                        "file_path": file_path,
                        "file_name": context_result.detected_filename,
                        "llm_request": llm_request,
                        "is_current_document": True,
                        "app_context": {
                            "app_name": context_result.app_name,
                            "bundle_id": context_result.bundle_id,
                            "window_title": context_result.window_title
                        }
                    }
            except Exception as e:
                logger.warning(f"Could not prepare file at detected path: {e}")
        
        # Step 3: Fallback - search for the file by name. This is the current-
        # document path, so it must resolve to a single prepared file, never a
        # candidate list; use confident_only to always prepare the best match.
        logger.info(f"🔍 Searching for file: {context_result.detected_filename}")
        search_result = await file_find_orchestrator.find_or_list_candidates(
            self.retrieval_service,
            self.cloud_service,
            context_result.detected_filename,
            f"{context} (detected from {context_result.app_name})",
            confident_only=True,
        )
        
        if search_result and search_result["success"]:
            # Enhance the result with detection information
            search_result.update({
                "detection_method": context_result.detection_method,
                "confidence": context_result.confidence,
                "is_current_document": True,
                "app_context": {
                    "app_name": context_result.app_name,
                    "bundle_id": context_result.bundle_id,
                    "window_title": context_result.window_title
                }
            })
            return search_result
        
        # Step 4: Complete failure
        logger.error(f"❌ Could not find or prepare file: {context_result.detected_filename}")
        return {
            "success": False,
            "error": f"Detected file '{context_result.detected_filename}' but could not locate or access it",
            "detection_result": context_result,
            "suggestions": [
                f"Manually search for '{context_result.detected_filename}'",
                "Check if the file exists and is accessible",
                "Try using the file search method with a broader search term"
            ]
        }
    
    def get_service_capabilities(self) -> Dict[str, Any]:
        """
        Return comprehensive capabilities of the file system service.
        
        Returns:
            Dict containing all available methods and their descriptions
        """
        return {
            "service_name": "file_system",
            "description": "Comprehensive file system operations including search, retrieval, and context detection",
            "version": "2.0",
            # Why these slim docs:
            # - file_service has only two methods so the discrimination is
            #   sharp: detect_and_prepare_current_document is the
            #   "this document / the file I have open" path, and
            #   find_file_for_llm is the "find a file by name" path.
            # - KEEPS that exact discriminating cue in the slim_doc; KEEPS
            #   the cross-reference to shell_service+mdfind for find-by-name
            #   workflows because that is the load-bearing 'native search
            #   first' invariant in execution_principles, and dropping it
            #   leads the agent to write recursive search loops.
            # - DROPS the use_cases list (the slim_doc inlines the cue),
            #   the returns shape (the agent learns it from a single result),
            #   and per-arg descriptions (Pydantic field descriptions cover
            #   them).
            "methods": [
                {
                    "name": "write_text_file",
                    "description": "Write direct UTF-8 text to a bounded local file without shell quoting.",
                    "slim_doc": (
                        "Create, replace, or append plain UTF-8 text at a known absolute local path. "
                        "Use this instead of shell redirection for text files so content is passed directly. "
                        "mode=create requires an absent target; mode=overwrite and mode=append require an existing regular file. "
                        "Optionally pass expected_sha256 after reading a file to reject a stale target. This tool does not create parent directories, follow symbolic links, write outside the allowed roots, or provide version rollback."
                    ),
                    "parameters": [
                        {"name": "path", "type": "str", "required": True, "description": "Absolute file path inside the allowed local roots."},
                        {"name": "content", "type": "str", "required": True, "description": "Exact UTF-8 text content to write directly."},
                        {"name": "mode", "type": "str", "required": True, "description": "One of create, overwrite, or append."},
                        {"name": "expected_sha256", "type": "Optional[str]", "required": False, "description": "Optional current-file SHA-256 required before overwrite or append."},
                    ],
                    "returns": "Dict with success, file_path, operation, bytes_written, prior and current SHA-256 digests, verified file_artifacts, and material_operation receipt.",
                },
                {
                    "name": "detect_and_prepare_current_document",
                    "description": "Detect and prepare the file currently being viewed ('take this document')",
                    "slim_doc": (
                        "Detect and prepare the file the user is currently "
                        "looking at - use when the request says 'this "
                        "document', 'the file I have open', 'current file', "
                        "or anything that clearly means the frontmost "
                        "document. Do NOT use when explicit reference_paths "
                        "are provided for the task; use those paths directly. "
                        "Do NOT use to search by name; for that, use "
                        "find_file_for_llm or shell_service + mdfind."
                    ),
                    "parameters": [
                        {
                            "name": "context",
                            "type": "str",
                            "required": False,
                            "description": "Additional context for LLM processing"
                        }
                    ],
                    "returns": "Dict with file content prepared for LLM, detection info, and app context",
                },
                {
                    "name": "find_file_for_llm",
                    "description": "Search for and prepare a file by name for LLM processing",
                    "slim_doc": (
                        "Search for a file by name across local, Spotlight-indexed, "
                        "AND cloud (Google Drive incl. 'Shared with me') locations, "
                        "then prepare its content. Returns result_kind='prepared' "
                        "(content ready) on a confident single match, or "
                        "result_kind='candidates' (a ranked list, NO content) when "
                        "several files match - in that case pick the right path and "
                        "call prepare_file_by_path to load it. Do not assume the most "
                        "recent candidate is correct."
                    ),
                    "parameters": [
                        {
                            "name": "filename",
                            "type": "str", 
                            "required": True,
                            "description": "Name of file to search for"
                        },
                        {
                            "name": "context",
                            "type": "str",
                            "required": False,
                            "description": "Additional context for LLM processing"
                        }
                    ],
                    "returns": "Dict: prepared file content, or a ranked candidate list to disambiguate",
                },
                {
                    "name": "prepare_file_by_path",
                    "description": "Prepare a specific file (by absolute path) for LLM processing",
                    "slim_doc": (
                        "Load and prepare a file's content when you already have its "
                        "absolute path - typically the follow-up after find_file_for_llm "
                        "returns result_kind='candidates' and you have chosen one. Also "
                        "use it when the task already provides an explicit file path."
                    ),
                    "parameters": [
                        {
                            "name": "path",
                            "type": "str",
                            "required": True,
                            "description": "Absolute path of the file to prepare"
                        },
                        {
                            "name": "context",
                            "type": "str",
                            "required": False,
                            "description": "Additional context for LLM processing"
                        }
                    ],
                    "returns": "Dict with file content prepared for LLM and metadata",
                }
            ],
            "features": [
                "Generic file context detection (95%+ accuracy)",
                "Local and cloud storage file search",
                "Multiple content encoding options (UTF-8, Base64)",
                "LLM-ready content preparation",
                "Comprehensive metadata extraction",
                "Accessibility API fallback detection",
                "Direct UTF-8 text creation, overwrite, and append",
                "Path-bounded verified material-operation receipts",
            ],
            "supported_applications": "All applications (generic pattern-based detection)",
            "supported_storage": [
                "Local file system",
                "Google Drive",
                "OneDrive", 
                "Dropbox",
                "iCloud"
            ],
            "detection_accuracy": "95%+ across major applications",
            "total_search_paths": len(self.default_search_paths) + len(self.cloud_search_paths),
            "execution_principles": [
                "NATIVE SEARCH FIRST: For finding files by name or content, prefer shell_service with mdfind/Spotlight before writing custom recursive search logic. mdfind is fast, index-based, and covers all mounted volumes including iCloud.",
                "CONTEXT DETECTION: Use detect_and_prepare_current_document when the user says 'this document', 'the file I have open', 'current file', or similar — do not search by name when the user clearly means the frontmost document.",
                "REFERENCE PATHS ARE AUTHORITATIVE: When the task context includes explicit reference_paths, operate on those paths directly. Do not use current-document detection to infer a different target from the active window.",
                "DIRECT TEXT WRITES: Use write_text_file for a known plain-text target instead of composing shell redirection. Read an existing file first and pass its SHA-256 as expected_sha256 when stale-write protection is needed.",
            ],
        }
    
    async def initialize(self) -> bool:
        """
        Initialize the file system service.
        
        Returns:
            True if initialization successful
        """
        logger.info("🔧 Initializing File System Service...")
        
        try:
            # Validate default search paths exist
            valid_paths = []
            for path in self.default_search_paths:
                if Path(path).exists():
                    valid_paths.append(path)
                    logger.info(f"   ✅ Search path available: {path}")
                else:
                    logger.warning(f"   ⚠️ Search path not found: {path}")
            
            self.default_search_paths = valid_paths
            
            # Detect and add cloud storage paths
            logger.info("🔍 Detecting cloud storage...")
            cloud_detection = await self.cloud_service.detect_cloud_storage()
            self.cloud_search_paths = cloud_detection.get('searchable_paths', [])
            
            if self.cloud_search_paths:
                logger.info(f"☁️  Found {len(self.cloud_search_paths)} cloud storage paths:")
                for path in self.cloud_search_paths:
                    logger.info(f"   ✅ Cloud path: {path}")
            else:
                logger.info("📋 No cloud storage detected")
            
            total_paths = len(valid_paths) + len(self.cloud_search_paths)
            logger.info(f"✅ File System Service initialized with {total_paths} search paths ({len(valid_paths)} local, {len(self.cloud_search_paths)} cloud)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize File System Service: {e}", exc_info=True)
            return False
    
    def _identify_cloud_provider(self, file_path: str) -> Optional[str]:
        """Identify which cloud provider a file path belongs to."""
        path_lower = file_path.lower()
        
        if 'google drive' in path_lower or 'googledrive' in path_lower:
            return 'google_drive'
        elif 'onedrive' in path_lower:
            return 'onedrive'
        elif 'dropbox' in path_lower:
            return 'dropbox'
        elif 'icloud' in path_lower or 'mobile documents' in path_lower:
            return 'icloud'
        else:
            return None 

    def _should_block_current_document_detection(self, context: Any) -> bool:
        agent_context = get_current_agent_context()
        reference_paths = agent_context.get("reference_paths") or []
        if not reference_paths:
            return False

        context_text = ""
        if isinstance(context, str):
            context_text = context.lower()
        elif isinstance(context, dict):
            context_text = " ".join(str(value).lower() for value in context.values() if isinstance(value, str))

        current_document_terms = (
            "current document",
            "current file",
            "frontmost document",
            "open document",
            "file i have open",
            "document i have open",
            "this document on screen",
            "this open file",
        )
        return not any(term in context_text for term in current_document_terms)