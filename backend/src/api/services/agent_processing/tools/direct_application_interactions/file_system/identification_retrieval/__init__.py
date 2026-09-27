"""
File System - Identification & Retrieval Services

Services focused on finding, detecting, and retrieving files:
- File context detection from current applications
- File search and retrieval operations  
- Cloud storage integration and search
"""

from .file_context_detection_service import FileContextDetectionService, FileContextResult
from .file_retrieval_service import FileRetrievalService
from .cloud_storage_service import CloudStorageService

__all__ = [
    'FileContextDetectionService',
    'FileContextResult', 
    'FileRetrievalService',
    'CloudStorageService'
] 