"""
File System Integration Package

Provides comprehensive file system operations for agent_tasks and automation.
Supports file search, retrieval, organization, and content modification.
"""

from .file_models import (
    FileType, ContentEncoding, FileContent, FileMetadata, LLMFileRequest
)
from .file_system_service import FileSystemService
from .anthropic_file_handler import AnthropicFileHandler

__all__ = [
    'FileType',
    'ContentEncoding', 
    'FileContent',
    'FileMetadata',
    'LLMFileRequest',
    'FileSystemService',
    'AnthropicFileHandler'
] 