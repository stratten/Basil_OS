"""
Anthropic File Handler

Handles Anthropic-specific file attachment formatting and validation.
Based on official Anthropic API documentation (2025).
"""

import logging
import base64
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

# Import existing file models
from .file_models import (
    FileType, ContentEncoding, FileContent, FileMetadata, LLMFileRequest
)

logger = logging.getLogger(__name__)


class AnthropicFileHandler:
    """
    Handles Anthropic-specific file attachment formatting and validation.
    
    Based on official Anthropic API documentation (2025):
    - Maximum request size: 32MB (total request including all content)
    - Maximum pages per request: 100 pages
    - All files use "document" content type (PDFs, images, text files)
    - Supported models: Claude Opus 4, Claude Sonnet 4, Claude 3.7 Sonnet, Claude 3.5 models, Claude Haiku 3.5
    """
    
    # Anthropic API limits (updated from official docs)
    MAX_REQUEST_SIZE = 32 * 1024 * 1024  # 32MB for entire request
    MAX_PAGES_PER_REQUEST = 100
    
    # All supported file types use "document" content type
    SUPPORTED_DOCUMENT_TYPES = {
        'pdf', 'txt', 'md', 'text'
    }
    
    # Image types that should use image content blocks
    SUPPORTED_IMAGE_TYPES = {
        'png', 'jpg', 'jpeg', 'gif', 'webp'
    }
    
    # All supported file types combined
    ALL_SUPPORTED_TYPES = SUPPORTED_DOCUMENT_TYPES | SUPPORTED_IMAGE_TYPES
    
    # MIME type mapping for Anthropic API
    MIME_TYPE_MAP = {
        # Document types
        'pdf': 'application/pdf',
        'txt': 'text/plain',
        'md': 'text/plain',
        'text': 'text/plain',
        
        # Image types
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg', 
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    
    async def load_files_from_paths(self, file_paths: List[str]) -> List[Dict[str, Any]]:
        """
        Load files from file paths and convert to file content format for Anthropic API.
        
        Args:
            file_paths: List of file paths to load
            
        Returns:
            List of file data dictionaries compatible with Anthropic API
        """
        file_contents = []
        
        for file_path in file_paths:
            try:
                file_path_obj = Path(file_path)
                
                if not file_path_obj.exists():
                    logger.warning(f"File not found: {file_path}")
                    continue
                
                # Read file content
                file_bytes = file_path_obj.read_bytes()
                base64_content = base64.b64encode(file_bytes).decode('utf-8')
                
                # Determine file type from extension
                file_extension = file_path_obj.suffix.lower().lstrip('.')
                file_type = file_extension if file_extension else 'txt'
                
                # Create file data structure
                file_data = {
                    'file_name': file_path_obj.name,
                    'file_type': file_type,
                    'file_size': len(file_bytes),
                    'base64_content': base64_content,
                    'content_encoding': 'base64',
                    'source_path': str(file_path_obj)  # Keep track of source for debugging
                }
                
                # Validate the file before adding
                validation_result = self.validate_file_content(file_data)
                if not validation_result['valid']:
                    logger.error(f"File validation failed for {file_path}: {validation_result['error']}")
                    continue
                
                file_contents.append(file_data)
                logger.info(f"✅ Loaded and validated file: {file_path_obj.name} ({file_data['file_size']} bytes)")
                
            except Exception as e:
                logger.error(f"Failed to load file {file_path}: {str(e)}")
                continue
        
        logger.info(f"📁 Successfully loaded {len(file_contents)} files from {len(file_paths)} paths")
        return file_contents
    
    def validate_file_content(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate file meets Anthropic API requirements.
        
        Args:
            file_data: Dictionary containing file information:
                {
                    'file_name': 'document.pdf',
                    'file_type': 'pdf', 
                    'file_size': 483195,
                    'base64_content': 'JVBERi0xLjQ...',
                    'content_encoding': 'base64'
                }
                
        Returns:
            {
                'valid': bool,
                'error': Optional[str],
                'mime_type': str|None
            }
        """
        try:
            file_name = file_data.get('file_name', 'unknown')
            file_type = file_data.get('file_type', '').lower()
            file_size = file_data.get('file_size', 0)
            base64_content = file_data.get('base64_content', '')
            
            logger.info(f"Validating file for Anthropic API: {file_name} (type: {file_type}, size: {file_size} bytes)")
            
            # Check if we have required data
            if not base64_content:
                return {
                    'valid': False,
                    'error': 'No base64 content provided',
                    'mime_type': None
                }
            
            # Check if file type is supported
            if file_type not in self.ALL_SUPPORTED_TYPES:
                return {
                    'valid': False,
                    'error': f'Unsupported file type: {file_type}. Supported types: {", ".join(sorted(self.ALL_SUPPORTED_TYPES))}',
                    'mime_type': None
                }
            
            # Note: Individual file size is checked against total request size limit
            # The 32MB limit applies to the entire request, not individual files
            # We'll do a rough check here, but the actual limit depends on total request size
            if file_size > self.MAX_REQUEST_SIZE:
                return {
                    'valid': False,
                    'error': f'File too large: {file_size} bytes. Maximum request size is {self.MAX_REQUEST_SIZE} bytes ({self.MAX_REQUEST_SIZE // (1024*1024)}MB) for entire request',
                    'mime_type': None
                }
            
            # Get MIME type
            mime_type = self.MIME_TYPE_MAP.get(file_type, 'application/octet-stream')
            
            logger.info(f"✅ File validation passed: {file_name} (document type, {mime_type})")
            return {
                'valid': True,
                'error': None,
                'mime_type': mime_type
            }
            
        except Exception as e:
            logger.error(f"Error validating file: {e}")
            return {
                'valid': False,
                'error': f'Validation error: {str(e)}',
                'mime_type': None
            }
    
    def format_for_anthropic_api(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format file content for Anthropic API message structure.
        
        Args:
            file_data: File data dictionary (same format as validate_file_content)
            
        Returns:
            Anthropic API content block:
            - For images: {'type': 'image', 'source': {...}}
            - For documents: {'type': 'document', 'source': {...}}
        """
        try:
            # First validate the file
            validation_result = self.validate_file_content(file_data)
            if not validation_result['valid']:
                raise ValueError(f"File validation failed: {validation_result['error']}")
            
            mime_type = validation_result['mime_type']
            base64_content = file_data.get('base64_content', '')
            file_type = file_data.get('file_type', '').lower()
            file_name = file_data.get('file_name', 'unknown')
            
            # CRITICAL: Use correct content block type based on file type
            if file_type in self.SUPPORTED_IMAGE_TYPES:
                # Images use "image" content blocks
                content_block = {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': mime_type,
                        'data': base64_content
                    }
                }
                logger.info(f"✅ Formatted file for Anthropic API: {file_name} as image ({mime_type})")
                
            elif file_type in self.SUPPORTED_DOCUMENT_TYPES:
                # Documents (PDFs, text) use "document" content blocks  
                content_block = {
                    'type': 'document',
                    'source': {
                        'type': 'base64',
                        'media_type': mime_type,
                        'data': base64_content
                    }
                }
                logger.info(f"✅ Formatted file for Anthropic API: {file_name} as document ({mime_type})")
                
            else:
                raise ValueError(f"Unsupported file type for Anthropic API: {file_type}")
            
            logger.info(f"🔍 [DEBUG] Content block type: {content_block['type']}")
            logger.info(f"🔍 [DEBUG] Source type: {content_block['source']['type']}")
            logger.info(f"🔍 [DEBUG] Media type: {content_block['source']['media_type']}")
            logger.info(f"🔍 [DEBUG] Data length: {len(content_block['source']['data'])} chars")
            logger.info(f"🔍 [DEBUG] Data preview: {content_block['source']['data'][:50]}...")
            
            return content_block
            
        except Exception as e:
            logger.error(f"Error formatting file for Anthropic API: {e}")
            raise
    
    def create_mixed_content_message(
        self, 
        text_prompt: str, 
        file_contents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Create message content with mixed text and file attachments.
        
        Args:
            text_prompt: The user's text prompt
            file_contents: List of file data dictionaries
            
        Returns:
            List of content blocks for Anthropic API
        """
        content_blocks = []
        total_size = 0
        
        # Start with the text prompt
        content_blocks.append({
            'type': 'text',
            'text': text_prompt
        })
        
        # Process each file
        for file_data in file_contents:
            file_name = file_data.get('file_name', 'unknown')
            file_type = file_data.get('file_type', '').lower()
            file_size = file_data.get('file_size', 0)
            
            # CRITICAL FIX: Handle text files differently than PDFs and images
            if file_type in ['txt', 'md', 'text']:
                # For text files, decode base64 and include directly in text content
                base64_content = file_data.get('base64_content', '')
                try:
                    # Decode base64 back to text
                    import base64
                    text_content = base64.b64decode(base64_content).decode('utf-8')
                    
                    # Add as text block, not document block
                    content_blocks.append({
                        'type': 'text', 
                        'text': f'\n\n--- File: {file_name} ---\n{text_content}\n--- End of {file_name} ---\n'
                    })
                    
                    logger.info(f"Added text file to message: {file_name} (included as text content)")
                    total_size += file_size
                    
                except Exception as e:
                    logger.error(f"Failed to decode text file {file_name}: {e}")
                    continue
            
            else:
                # For PDFs, images, and other documents, use appropriate content blocks
                try:
                    # Format as document or image block
                    content_block = self.format_for_anthropic_api(file_data)
                    content_blocks.append(content_block)
                    
                    block_type = "image" if file_type in self.SUPPORTED_IMAGE_TYPES else "document"
                    logger.info(f"Added {block_type} to message: {file_name} (total size: {total_size + file_size} bytes)")
                    total_size += file_size
                    
                except Exception as e:
                    logger.error(f"Failed to format file {file_name} for Anthropic API: {e}")
                    continue
        
        logger.info(f"✅ Created mixed content message with {len(content_blocks)} blocks ({len([f for f in file_contents])} files, {total_size} bytes total)")
        return content_blocks
    
    def get_supported_file_types(self) -> List[str]:
        """
        Get the file types supported by Anthropic API.
        
        Returns:
            List of supported file extensions
        """
        return list(sorted(self.ALL_SUPPORTED_TYPES))
    
    def get_api_limits(self) -> Dict[str, Any]:
        """
        Get API limits for Anthropic file handling.
        
        Returns:
            Dictionary with current API limits
        """
        return {
            'max_request_size_bytes': self.MAX_REQUEST_SIZE,
            'max_request_size_mb': self.MAX_REQUEST_SIZE // (1024 * 1024),
            'max_pages_per_request': self.MAX_PAGES_PER_REQUEST,
            'supported_file_types': self.get_supported_file_types(),
            'content_block_type': 'document',  # All files use 'document' type
            'notes': [
                'The 32MB limit applies to the entire request, not individual files',
                'All file types (PDFs, images, text) use the same "document" content type',
                'Supported on Claude Opus 4, Sonnet 4, 3.7 Sonnet, 3.5 models, and Haiku 3.5'
            ]
        }
    
    def validate_request_size(self, file_contents: List[Dict[str, Any]], additional_content: str = '') -> Dict[str, Any]:
        """
        Validate that the total request size is within Anthropic limits.
        

            file_contents: List of file data dictionaries
            additional_content: Any additional text content in the request
            
        Returns:
            {
                'valid': bool,
                'total_size': int,
                'error': Optional[str],
                'files_that_fit': List[Dict],
                'files_excluded': List[Dict]
            }
        """
        try:
            total_size = len(additional_content.encode('utf-8'))
            files_that_fit = []
            files_excluded = []
            
            for file_data in file_contents:
                file_size = file_data.get('file_size', 0)
                
                if total_size + file_size <= self.MAX_REQUEST_SIZE:
                    files_that_fit.append(file_data)
                    total_size += file_size
                else:
                    files_excluded.append(file_data)
            
            return {
                'valid': len(files_excluded) == 0,
                'total_size': total_size,
                'error': f'{len(files_excluded)} files excluded due to size limits' if files_excluded else None,
                'files_that_fit': files_that_fit,
                'files_excluded': files_excluded
            }
            
        except Exception as e:
            logger.error(f"Error validating request size: {e}")
            return {
                'valid': False,
                'total_size': 0,
                'error': f'Size validation error: {str(e)}',
                'files_that_fit': [],
                'files_excluded': file_contents
            }
    
    def extract_file_info_from_llm_request(self, llm_request: LLMFileRequest) -> Dict[str, Any]:
        """
        Extract file information from an LLMFileRequest for Anthropic processing.
        
        Args:
            llm_request: LLMFileRequest object from FileSystemService
            
        Returns:
            File data dictionary compatible with other methods
        """
        try:
            file_content = llm_request.file_content
            metadata = file_content.metadata
            
            # Extract file extension and type
            file_path = Path(file_content.file_path)
            file_extension = file_path.suffix.lstrip('.').lower()
            
            # Map FileType enum to string
            file_type_str = file_extension
            if metadata and metadata.file_type:
                type_mapping = {
                    FileType.PDF: 'pdf',
                    FileType.TEXT: 'txt',
                    FileType.IMAGE: file_extension,  # Use actual extension for images
                    FileType.DOCUMENT: file_extension,
                    # Add more mappings as needed
                }
                file_type_str = type_mapping.get(metadata.file_type, file_extension)
            
            return {
                'file_name': metadata.name if metadata else file_path.name,
                'file_type': file_type_str,
                'file_size': metadata.size if metadata else file_content.content_size,
                'base64_content': file_content.base64_content,
                'content_encoding': file_content.content_type.value,
                'file_path': file_content.file_path
            }
            
        except Exception as e:
            logger.error(f"Error extracting file info from LLMFileRequest: {e}")
            raise ValueError(f"Failed to extract file info: {str(e)}") 