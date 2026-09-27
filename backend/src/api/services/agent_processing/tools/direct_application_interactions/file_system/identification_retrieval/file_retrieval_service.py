"""
File Retrieval Service

Core service for finding, reading, and preparing files for LLM integration.
Supports Spotlight search, content extraction, and Base64 encoding for Anthropic.
"""

import asyncio
import logging
import subprocess
import os
import mimetypes
import base64
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path

from ..file_models import (
    FileSearchCriteria, FileMetadata, FileContent, FileSearchResult,
    FileType, ContentEncoding, LLMFileRequest
)

logger = logging.getLogger(__name__)


class FileRetrievalService:
    """
    Service for finding and retrieving files for LLM processing.
    
    Primary use case: "Take this document and draft a reply to this email"
    - Search for files by name using Spotlight
    - Extract and encode file content for LLM requests
    - Support multiple content encoding methods (UTF-8, Base64)
    """
    
    def __init__(self):
        self.max_file_size = 100 * 1024 * 1024  # 100MB default limit
        self.supported_text_extensions = {
            '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml',
            '.csv', '.log', '.conf', '.cfg', '.ini', '.yaml', '.yml'
        }
        self.spotlight_timeout = 10  # seconds
        
    async def search_files_by_name(self, filename: str, search_paths: Optional[List[str]] = None) -> FileSearchResult:
        """
        Search for files by name using macOS Spotlight.
        
        Args:
            filename: Name or partial name to search for
            search_paths: Optional specific paths to search in
            
        Returns:
            FileSearchResult with found files
        """
        logger.info(f"🔍 Searching for files matching: '{filename}'")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Use Spotlight (mdfind) for fast file searching
            files_found = await self._spotlight_search(filename, search_paths)
            
            search_duration = asyncio.get_event_loop().time() - start_time
            
            # Create search criteria for the result
            criteria = FileSearchCriteria(
                name_contains=filename,
                search_paths=search_paths or []
            )
            
            result = FileSearchResult(
                query=criteria,
                files_found=files_found,
                search_duration=search_duration,
                total_results=len(files_found),
                search_method="spotlight"
            )
            
            logger.info(f"🔍 Found {len(files_found)} files in {search_duration:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error searching files: {e}", exc_info=True)
            return FileSearchResult(
                query=FileSearchCriteria(name_contains=filename),
                files_found=[],
                search_duration=asyncio.get_event_loop().time() - start_time,
                total_results=0,
                search_method="spotlight",
                errors=[str(e)]
            )
    
    async def _spotlight_search(self, filename: str, search_paths: Optional[List[str]] = None) -> List[FileMetadata]:
        """Use macOS Spotlight to search for files."""
        cmd = ["mdfind"]
        
        # Build search query
        if search_paths:
            # Search in specific directories
            for path in search_paths:
                cmd.extend(["-onlyin", path])
        
        # Search for filename
        cmd.append(f"kMDItemDisplayName == '*{filename}*'c")
        
        logger.info(f"🔍 Spotlight command: {' '.join(cmd)}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.spotlight_timeout
            )
            
            if process.returncode != 0:
                logger.warning(f"⚠️ Spotlight search warning: {stderr.decode()}")
            
            # Parse results
            file_paths = stdout.decode().strip().split('\n')
            file_paths = [path for path in file_paths if path]  # Remove empty lines
            
            # Get metadata for each file
            files_metadata = []
            for file_path in file_paths:
                try:
                    metadata = await self._get_file_metadata(file_path)
                    if metadata:
                        files_metadata.append(metadata)
                except Exception as e:
                    logger.debug(f"⚠️ Could not get metadata for {file_path}: {e}")
            
            return files_metadata
            
        except asyncio.TimeoutError:
            logger.error(f"⏰ Spotlight search timed out after {self.spotlight_timeout}s")
            return []
        except Exception as e:
            logger.error(f"❌ Spotlight search error: {e}")
            return []
    
    async def _get_file_metadata(self, file_path: str) -> Optional[FileMetadata]:
        """Extract metadata from a file."""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                return None
            
            # Skip directories - we only want files
            if path_obj.is_dir():
                logger.debug(f"⚠️ Skipping directory: {file_path}")
                return None
            
            stat = path_obj.stat()
            
            # Determine file type
            file_type = self._determine_file_type(path_obj)
            
            # Get MIME type
            mime_type, _ = mimetypes.guess_type(file_path)
            
            metadata = FileMetadata(
                path=str(path_obj.absolute()),
                name=path_obj.name,
                size=stat.st_size,
                created_date=datetime.fromtimestamp(stat.st_ctime),
                modified_date=datetime.fromtimestamp(stat.st_mtime),
                accessed_date=datetime.fromtimestamp(stat.st_atime),
                file_type=file_type,
                extension=path_obj.suffix.lower(),
                mime_type=mime_type,
                is_readable=os.access(file_path, os.R_OK),
                is_writable=os.access(file_path, os.W_OK)
            )
            
            return metadata
            
        except Exception as e:
            logger.error(f"❌ Error getting metadata for {file_path}: {e}")
            return None
    
    def _determine_file_type(self, path: Path) -> FileType:
        """Determine file type based on extension."""
        ext = path.suffix.lower()
        
        if ext in self.supported_text_extensions:
            return FileType.TEXT
        elif ext in {'.pdf'}:
            return FileType.PDF
        elif ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.svg'}:
            return FileType.IMAGE
        elif ext in {'.doc', '.docx', '.pages', '.rtf', '.odt'}:
            return FileType.DOCUMENT
        elif ext in {'.xls', '.xlsx', '.numbers', '.csv', '.ods'}:
            return FileType.SPREADSHEET
        elif ext in {'.ppt', '.pptx', '.key', '.odp'}:
            return FileType.PRESENTATION
        elif ext in {'.zip', '.rar', '.7z', '.tar', '.gz', '.dmg'}:
            return FileType.ARCHIVE
        else:
            return FileType.UNKNOWN
    
    async def read_file_content(self, file_path: str, 
                              encoding: ContentEncoding = ContentEncoding.UTF8_TEXT) -> Optional[FileContent]:
        """
        Read file content and prepare it for LLM integration.
        
        Args:
            file_path: Path to the file to read
            encoding: Preferred encoding method
            
        Returns:
            FileContent object with encoded content
        """
        logger.info(f"📖 Reading file: {file_path}")
        logger.info(f"📖 Encoding preference: {encoding.value}")
        
        try:
            # Get file metadata first
            metadata = await self._get_file_metadata(file_path)
            if not metadata:
                logger.error(f"❌ Could not get metadata for {file_path}")
                return None
            
            # Check file size
            if metadata.size > self.max_file_size:
                logger.error(f"❌ File too large: {metadata.size} bytes (max: {self.max_file_size})")
                return None
            
            # Check readability
            if not metadata.is_readable:
                logger.error(f"❌ File not readable: {file_path}")
                return None
            
            # Read file content based on type and encoding preference
            if metadata.file_type == FileType.TEXT and encoding == ContentEncoding.UTF8_TEXT:
                return await self._read_text_file(file_path, metadata)
            elif encoding == ContentEncoding.BASE64:
                return await self._read_file_as_base64(file_path, metadata)
            elif encoding == ContentEncoding.EXTRACTED_TEXT:
                return await self._extract_text_content(file_path, metadata)
            else:
                # Default to Base64 for non-text files
                return await self._read_file_as_base64(file_path, metadata)
                
        except Exception as e:
            logger.error(f"❌ Error reading file {file_path}: {e}", exc_info=True)
            return None
    
    async def _read_text_file(self, file_path: str, metadata: FileMetadata) -> FileContent:
        """Read a text file as UTF-8."""
        logger.info(f"📄 Reading as UTF-8 text: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return FileContent(
                file_path=file_path,
                content_type=ContentEncoding.UTF8_TEXT,
                raw_content=content,
                extracted_text=content,  # Same as raw for text files
                metadata=metadata,
                extraction_method="direct_utf8_read"
            )
            
        except UnicodeDecodeError:
            # Fallback to Base64 if UTF-8 fails
            logger.warning(f"⚠️ UTF-8 decode failed for {file_path}, falling back to Base64")
            return await self._read_file_as_base64(file_path, metadata)
    
    async def _read_file_as_base64(self, file_path: str, metadata: FileMetadata) -> FileContent:
        """Read any file as Base64 encoded content."""
        logger.info(f"📦 Reading as Base64: {file_path}")
        
        with open(file_path, 'rb') as f:
            raw_bytes = f.read()
        
        base64_content = base64.b64encode(raw_bytes).decode('utf-8')
        
        return FileContent(
            file_path=file_path,
            content_type=ContentEncoding.BASE64,
            raw_content=raw_bytes,
            base64_content=base64_content,
            metadata=metadata,
            extraction_method="base64_encoding"
        )
    
    async def _extract_text_content(self, file_path: str, metadata: FileMetadata) -> Optional[FileContent]:
        """Extract text content from non-text files (PDF, Word, etc.)."""
        logger.info(f"📝 Extracting text from: {file_path}")
        
        # This is a placeholder for future text extraction capabilities
        # Could integrate with libraries like PyPDF2, python-docx, etc.
        
        if metadata.file_type == FileType.PDF:
            # Future: Use PyPDF2 or pdfplumber
            logger.warning(f"⚠️ PDF text extraction not yet implemented for {file_path}")
            return await self._read_file_as_base64(file_path, metadata)
        elif metadata.file_type == FileType.DOCUMENT:
            # Future: Use python-docx for Word docs
            logger.warning(f"⚠️ Document text extraction not yet implemented for {file_path}")
            return await self._read_file_as_base64(file_path, metadata)
        else:
            # Default to Base64 for unsupported types
            return await self._read_file_as_base64(file_path, metadata)
    
    async def prepare_file_for_llm(self, file_path: str, prompt_context: str = "", 
                                 encoding_preference: ContentEncoding = ContentEncoding.BASE64) -> Optional[LLMFileRequest]:
        """
        Prepare a file for LLM processing with context.
        
        Args:
            file_path: Path to the file
            prompt_context: Additional context for the LLM prompt
            encoding_preference: Preferred encoding method
            
        Returns:
            LLMFileRequest ready for LLM integration
        """
        logger.info(f"🤖 Preparing file for LLM: {file_path}")
        
        try:
            # Read file content
            file_content = await self.read_file_content(file_path, encoding_preference)
            if not file_content:
                return None
            
            # Create LLM request
            llm_request = LLMFileRequest(
                file_path=file_path,
                file_content=file_content,
                prompt_context=prompt_context,
                encoding_preference=encoding_preference,
                include_metadata=True
            )
            
            logger.info(f"✅ File prepared for LLM: {file_content.content_size} bytes")
            return llm_request
            
        except Exception as e:
            logger.error(f"❌ Error preparing file for LLM: {e}", exc_info=True)
            return None
    
    async def find_and_prepare_file(self, filename: str, prompt_context: str = "", 
                                  search_paths: Optional[List[str]] = None) -> Optional[LLMFileRequest]:
        """
        Complete workflow: Find file by name and prepare for LLM.
        
        This is the main method for the "take this document and draft a reply" workflow.
        
        Args:
            filename: Name of file to search for
            prompt_context: Context to include with the file
            search_paths: Optional paths to search in
            
        Returns:
            LLMFileRequest ready for processing, or None if file not found
        """
        logger.info(f"🎯 Find and prepare workflow: '{filename}'")
        
        try:
            # Step 1: Search for the file
            search_result = await self.search_files_by_name(filename, search_paths)
            
            if not search_result.files_found:
                logger.warning(f"⚠️ No files found matching '{filename}'")
                return None
            
            # Step 2: Select the best match (most recent if multiple)
            if len(search_result.files_found) > 1:
                logger.info(f"🔍 Found {len(search_result.files_found)} files, selecting most recent")
                best_file = max(search_result.files_found, key=lambda f: f.modified_date)
            else:
                best_file = search_result.files_found[0]
            
            logger.info(f"📋 Selected file: {best_file.name} ({best_file.path})")
            
            # Step 3: Prepare for LLM
            llm_request = await self.prepare_file_for_llm(
                best_file.path, 
                prompt_context, 
                ContentEncoding.BASE64  # Default to Base64 for Anthropic
            )
            
            if llm_request:
                logger.info(f"✅ File ready for LLM processing: {best_file.name}")
            
            return llm_request
            
        except Exception as e:
            logger.error(f"❌ Find and prepare workflow failed: {e}", exc_info=True)
            return None 