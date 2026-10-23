"""
File System Data Models

Dataclasses and type definitions for file system automation services.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pathlib import Path
from enum import Enum


class FileType(Enum):
    """Supported file types for content extraction."""
    TEXT = "text"
    PDF = "pdf"
    IMAGE = "image"
    DOCUMENT = "document"  # Word, Pages, etc.
    SPREADSHEET = "spreadsheet"  # Excel, Numbers, etc.
    PRESENTATION = "presentation"  # PowerPoint, Keynote, etc.
    ARCHIVE = "archive"  # ZIP, RAR, etc.
    UNKNOWN = "unknown"


class ContentEncoding(Enum):
    """Content encoding methods for LLM integration."""
    UTF8_TEXT = "utf8_text"
    BASE64 = "base64"
    EXTRACTED_TEXT = "extracted_text"


@dataclass
class FileSearchCriteria:
    """Criteria for searching files."""
    name_contains: Optional[str] = None
    exact_name: Optional[str] = None
    file_extension: Optional[str] = None
    content_contains: Optional[str] = None
    modified_after: Optional[datetime] = None
    modified_before: Optional[datetime] = None
    size_min: Optional[int] = None  # bytes
    size_max: Optional[int] = None  # bytes
    search_paths: List[str] = None  # Specific directories to search
    exclude_paths: List[str] = None  # Directories to exclude
    file_types: List[FileType] = None  # Limit to specific file types
    
    def __post_init__(self):
        if self.search_paths is None:
            self.search_paths = []
        if self.exclude_paths is None:
            self.exclude_paths = []
        if self.file_types is None:
            self.file_types = []


@dataclass
class FileMetadata:
    """File metadata and properties."""
    path: str
    name: str
    size: int  # bytes
    created_date: datetime
    modified_date: datetime
    accessed_date: datetime
    file_type: FileType
    extension: str
    mime_type: Optional[str] = None
    is_readable: bool = True
    is_writable: bool = True
    parent_directory: Optional[str] = None
    
    def __post_init__(self):
        if self.parent_directory is None:
            self.parent_directory = str(Path(self.path).parent)


@dataclass
class FileContent:
    """File content with multiple encoding options."""
    file_path: str
    content_type: ContentEncoding
    raw_content: Union[str, bytes]  # UTF-8 text or raw bytes
    extracted_text: Optional[str] = None  # Extracted text for non-text files
    base64_content: Optional[str] = None  # Base64 encoded content
    metadata: Optional[FileMetadata] = None
    extraction_method: Optional[str] = None  # How content was extracted
    content_size: int = 0  # Size of content in bytes
    
    def __post_init__(self):
        if isinstance(self.raw_content, bytes):
            self.content_size = len(self.raw_content)
        elif isinstance(self.raw_content, str):
            self.content_size = len(self.raw_content.encode('utf-8'))


@dataclass
class FileSearchResult:
    """Result of a file search operation."""
    query: FileSearchCriteria
    files_found: List[FileMetadata]
    search_duration: float  # seconds
    total_results: int
    search_method: str  # "spotlight", "filesystem", "hybrid"
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.total_results == 0:
            self.total_results = len(self.files_found)


@dataclass
class FileOperation:
    """Represents a file operation request."""
    operation: str  # "read", "search", "move", "copy", "delete", "rename"
    target_files: List[str]  # File paths
    destination: Optional[str] = None  # For move/copy operations
    new_name: Optional[str] = None  # For rename operations
    create_backup: bool = False
    overwrite_existing: bool = False
    
    
@dataclass
class LLMFileRequest:
    """Request to process file content with LLM."""
    file_path: str
    file_content: FileContent
    prompt_context: str  # Additional context for LLM
    encoding_preference: ContentEncoding = ContentEncoding.UTF8_TEXT
    max_content_size: int = 50 * 1024 * 1024  # 50MB default limit
    include_metadata: bool = True 