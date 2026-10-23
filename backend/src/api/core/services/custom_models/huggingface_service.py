"""
HuggingFace Integration Service.

Provides repository probing and metadata extraction for HuggingFace models.
"""

import logging
from typing import List, Optional

from .schemas import (
    HFFileInfo,
    HFModelMetadata,
    HFProbeRequest,
    HFProbeResponse,
)


logger = logging.getLogger(__name__)


# =============================================================================
# UTILITIES
# =============================================================================


def format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def normalize_hf_url(url: str) -> str:
    """Convert various HuggingFace URL formats to a repo_id.
    
    Accepts:
    - Full URL: https://huggingface.co/TheBloke/Llama-2-7B-GGUF
    - URL with paths: https://huggingface.co/TheBloke/Llama-2-7B-GGUF/tree/main
    - Direct file URL: https://huggingface.co/TheBloke/Llama-2-7B-GGUF/resolve/main/file.gguf
    - Simple repo_id: TheBloke/Llama-2-7B-GGUF
    """
    url = url.strip()
    
    # Already a repo_id (e.g., "TheBloke/Llama-2-7B-GGUF")
    if "/" in url and not url.startswith("http"):
        return url
    
    # Full URL formats
    url = url.replace("https://huggingface.co/", "")
    url = url.replace("http://huggingface.co/", "")
    
    # Strip tree/main, blob/main paths
    for suffix in ["/tree/main", "/blob/main", "/tree/master", "/blob/master"]:
        if suffix in url:
            url = url.split(suffix)[0]
            break
    
    # If it's a direct file URL, extract just the repo part
    if "/resolve/" in url:
        url = url.split("/resolve/")[0]
    
    # Remove trailing slashes
    url = url.rstrip("/")
    
    return url


# =============================================================================
# HUGGINGFACE SERVICE
# =============================================================================


class HuggingFaceService:
    """Integration with HuggingFace Hub for model discovery and metadata extraction."""
    
    def find_source_repo(self, repo_id: str) -> Optional[str]:
        """Try to find the source repo for a GGUF derivative repo.
        
        Common patterns:
        - microsoft/Phi-3-mini-4k-instruct-gguf -> microsoft/Phi-3-mini-4k-instruct
        - TheBloke/Llama-2-7B-GGUF -> meta-llama/Llama-2-7b (harder to determine)
        """
        suffixes_to_strip = ["-gguf", "-GGUF", "_gguf", "_GGUF", "-ggml", "-GGML"]
        for suffix in suffixes_to_strip:
            if repo_id.endswith(suffix):
                return repo_id[:-len(suffix)]
        return None
    
    def extract_model_metadata(self, api, repo_id: str, files_info: List[str]) -> Optional[HFModelMetadata]:
        """Extract model metadata from config.json if available."""
        import json
        from huggingface_hub import hf_hub_download
        
        logger.info(f"[HF Metadata] Checking for config.json in {repo_id}")
        logger.info(f"[HF Metadata] Available files: {[f for f in files_info if f.endswith('.json')][:10]}")
        
        # Check if config.json exists in this repo
        target_repo = repo_id
        if "config.json" not in files_info:
            logger.info(f"[HF Metadata] No config.json in {repo_id}, trying source repo...")
            
            # Try to find the source repo (for GGUF derivative repos)
            source_repo = self.find_source_repo(repo_id)
            if source_repo:
                logger.info(f"[HF Metadata] Trying source repo: {source_repo}")
                try:
                    source_files = api.list_repo_files(source_repo)
                    if "config.json" in source_files:
                        target_repo = source_repo
                        logger.info(f"[HF Metadata] Found config.json in source repo: {source_repo}")
                    else:
                        logger.info(f"[HF Metadata] No config.json in source repo either")
                        return None
                except Exception as e:
                    logger.info(f"[HF Metadata] Could not access source repo {source_repo}: {e}")
                    return None
            else:
                logger.info(f"[HF Metadata] Could not determine source repo for {repo_id}")
                return None
        
        try:
            logger.info(f"[HF Metadata] Downloading config.json from {target_repo}")
            
            # Download config.json
            config_path = hf_hub_download(
                repo_id=target_repo,
                filename="config.json",
                cache_dir=None,  # Use default cache
            )
            
            logger.info(f"[HF Metadata] Downloaded to: {config_path}")
            
            with open(config_path, "r") as f:
                config = json.load(f)
            
            logger.info(f"[HF Metadata] Config keys: {list(config.keys())}")
            
            # Extract context window - try multiple common field names
            context_window = None
            checked_fields = []
            for field in [
                "max_position_embeddings",  # Most common (BERT, GPT, Llama, etc.)
                "n_positions",               # GPT-2 style
                "max_seq_length",            # Some models
                "seq_length",                # Alternative
                "context_length",            # Direct naming
                "max_length",                # Alternative
                "sliding_window",            # Mistral-style
            ]:
                checked_fields.append(field)
                if field in config:
                    context_window = config[field]
                    logger.info(f"[HF Metadata] ✅ Found context window in '{field}': {context_window}")
                    break
            
            if context_window is None:
                logger.info(f"[HF Metadata] ❌ No context window found. Checked: {checked_fields}")
            
            # Extract model type
            model_type = config.get("model_type")
            logger.info(f"[HF Metadata] model_type: {model_type}")
            
            # Extract architecture info
            architectures = config.get("architectures", [])
            architecture = architectures[0] if architectures else None
            logger.info(f"[HF Metadata] architecture: {architecture}")
            
            if context_window or model_type or architecture:
                result = HFModelMetadata(
                    context_window=context_window,
                    model_type=model_type,
                    architecture=architecture,
                )
                logger.info(f"[HF Metadata] Returning metadata: {result}")
                return result
            
            logger.info(f"[HF Metadata] No useful metadata found")
            return None
            
        except Exception as e:
            logger.warning(f"[HF Metadata] Failed to extract metadata from config.json: {e}")
            import traceback
            logger.warning(f"[HF Metadata] Traceback: {traceback.format_exc()}")
            return None
    
    async def probe_repo(self, request: HFProbeRequest) -> HFProbeResponse:
        """List available model files in a HuggingFace repository.
        
        Accepts various URL formats and returns categorized lists of GGUF
        and SafeTensor files available for download. Also attempts to extract
        model metadata from config.json if available.
        """
        try:
            from huggingface_hub import HfApi
            
            # Normalize the URL to a repo_id.
            repo_id = normalize_hf_url(request.url)
            logger.info(f"Probing HuggingFace repo: {repo_id}")
            
            # Get repository files with metadata.
            api = HfApi()
            files_info = api.list_repo_files(repo_id)
            
            # Try to get file sizes (requires repo_info with files_metadata).
            file_sizes = {}
            try:
                repo_info = api.repo_info(repo_id, files_metadata=True)
                if repo_info.siblings:
                    for sibling in repo_info.siblings:
                        if hasattr(sibling, 'size') and sibling.size is not None:
                            file_sizes[sibling.rfilename] = sibling.size
                            logger.debug(f"[HF Probe] File size for {sibling.rfilename}: {sibling.size}")
                    logger.info(f"[HF Probe] Extracted sizes for {len(file_sizes)} files")
                else:
                    logger.warning("[HF Probe] repo_info.siblings is empty or None")
            except Exception as e:
                logger.warning(f"[HF Probe] Failed to get file sizes: {e}")
            
            # Filter and categorize files.
            gguf_files: List[HFFileInfo] = []
            safetensor_files: List[HFFileInfo] = []
            
            for filename in files_info:
                size_bytes = file_sizes.get(filename)
                file_info = HFFileInfo(
                    name=filename,
                    size_bytes=size_bytes,
                    size_human=format_size(size_bytes) if size_bytes else None,
                )
                
                if filename.endswith(".gguf"):
                    gguf_files.append(file_info)
                elif filename.endswith(".safetensors"):
                    safetensor_files.append(file_info)
            
            logger.info(f"Found {len(gguf_files)} GGUF, {len(safetensor_files)} safetensor files")
            
            # Extract model metadata from config.json
            model_metadata = self.extract_model_metadata(api, repo_id, files_info)
            if model_metadata:
                logger.info(f"Extracted metadata: context_window={model_metadata.context_window}, model_type={model_metadata.model_type}")
            
            return HFProbeResponse(
                repo_id=repo_id,
                gguf_files=gguf_files,
                safetensor_files=safetensor_files,
                model_metadata=model_metadata,
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to probe HuggingFace repo: {error_msg}")
            return HFProbeResponse(
                repo_id=normalize_hf_url(request.url),
                gguf_files=[],
                safetensor_files=[],
                model_metadata=None,
                error=error_msg,
            )


    async def get_gguf_file_metadata(self, repo_id: str, filename: str) -> Optional[HFModelMetadata]:
        """Fetch GGUF file metadata via partial download (first 256KB).
        
        Uses HTTP Range request to download only the header portion of a GGUF file,
        then parses it to extract context_length, architecture, and other metadata.
        This allows metadata extraction before committing to a multi-GB download.
        """
        import tempfile
        import httpx
        
        logger.info(f"[GGUF Partial] Fetching header for {repo_id}/{filename}")
        
        # Build the raw file URL for HuggingFace
        # Format: https://huggingface.co/{repo_id}/resolve/main/{filename}
        file_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
        
        try:
            # Fetch first 256KB using Range header
            # GGUF headers are typically much smaller, but we want to be safe
            headers = {"Range": "bytes=0-262143"}  # First 256KB
            
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(file_url, headers=headers)
                
                if response.status_code not in (200, 206):  # 206 = Partial Content
                    logger.warning(f"[GGUF Partial] Failed to fetch: HTTP {response.status_code}")
                    return None
                
                partial_data = response.content
                logger.info(f"[GGUF Partial] Downloaded {len(partial_data)} bytes")
            
            # Verify it's a GGUF file (magic number)
            if len(partial_data) < 4 or partial_data[:4] != b'GGUF':
                logger.warning(f"[GGUF Partial] Not a valid GGUF file (magic: {partial_data[:4]})")
                return None
            
            # Save to temp file for GGUFReader
            with tempfile.NamedTemporaryFile(suffix='.gguf', delete=False) as tmp:
                tmp.write(partial_data)
                tmp_path = tmp.name
            
            try:
                return self._parse_gguf_header(tmp_path, filename)
            finally:
                # Clean up temp file
                import os
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                    
        except Exception as e:
            logger.warning(f"[GGUF Partial] Failed to fetch/parse header: {e}")
            import traceback
            logger.debug(f"[GGUF Partial] Traceback: {traceback.format_exc()}")
            return None
    
    def _parse_gguf_header(self, file_path: str, original_filename: str) -> Optional[HFModelMetadata]:
        """Parse GGUF header from a partial file using GGUFReader.
        
        Uses a subclassed GGUFReader that stops after reading metadata fields,
        skipping tensor data which isn't present in partial downloads.
        Falls back to manual parsing if the gguf library isn't available.
        """
        try:
            from gguf.gguf_reader import GGUFReader, ReaderField, READER_SUPPORTED_VERSIONS
            from gguf.constants import GGUF_MAGIC, GGUFValueType
            import numpy as np
            from collections import OrderedDict
            from typing import Literal
            
            class GGUFMetadataReader(GGUFReader):
                """GGUFReader subclass that only reads metadata, not tensor data.
                
                Designed for partial file downloads where tensor data isn't present.
                """
                
                def __init__(self, path, mode: Literal['r', 'r+', 'c'] = 'r'):
                    self.data = np.memmap(path, mode=mode)
                    offs = 0

                    # Check for GGUF magic
                    if self._get(offs, np.uint32, override_order='<')[0] != GGUF_MAGIC:
                        raise ValueError('GGUF magic invalid')
                    offs += 4

                    # Check GGUF version
                    temp_version = self._get(offs, np.uint32)
                    if temp_version[0] & 65535 == 0:
                        self.byte_order = 'S'
                        temp_version = temp_version.newbyteorder(self.byte_order)
                    version = temp_version[0]
                    if version not in READER_SUPPORTED_VERSIONS:
                        raise ValueError(f'Unsupported GGUF version {version}')
                    
                    self.fields: OrderedDict[str, ReaderField] = OrderedDict()
                    self.tensors = []  # Empty - we skip tensor reading
                    offs += self._push_field(ReaderField(offs, 'GGUF.version', [temp_version], [0], [GGUFValueType.UINT32]))

                    # Read tensor count and kv count
                    temp_counts = self._get(offs, np.uint64, 2)
                    offs += self._push_field(ReaderField(offs, 'GGUF.tensor_count', [temp_counts[:1]], [0], [GGUFValueType.UINT64]))
                    offs += self._push_field(ReaderField(offs, 'GGUF.kv_count', [temp_counts[1:]], [0], [GGUFValueType.UINT64]))
                    tensor_count, kv_count = temp_counts
                    
                    # Build metadata fields - may error on partial files, that's okay
                    try:
                        self._build_fields(offs, kv_count)
                    except Exception:
                        # Partial file - fields read so far are still valid
                        pass
                    
                    # DO NOT call _build_tensor_info or _build_tensors
            
            # Use our metadata-only reader
            reader = GGUFMetadataReader(file_path)
            
            context_window = None
            model_type = None
            architecture = None
            model_name = None
            
            # Keys that contain string values (need byte decoding)
            string_keys = {'general.architecture', 'general.name'}
            # Keys that contain numeric values
            numeric_key_patterns = ['context_length', '.n_ctx']
            
            for key, field in reader.fields.items():
                key_lower = key.lower()
                
                try:
                    # Extract value from field parts
                    if not field.parts:
                        continue
                    
                    last_part = field.parts[-1]
                    if not hasattr(last_part, 'tolist'):
                        continue
                    
                    values = last_part.tolist()
                    if not values:
                        continue
                    
                    # Determine if this is a string or numeric field
                    is_string_field = key_lower in string_keys
                    is_numeric_field = any(p in key_lower for p in numeric_key_patterns)
                    
                    if is_string_field:
                        # Decode bytes as UTF-8 string
                        try:
                            value = bytes(values).decode('utf-8').rstrip('\x00')
                        except:
                            value = None
                    elif is_numeric_field:
                        # Take as numeric value
                        value = values[0] if isinstance(values[0], (int, float)) else None
                    else:
                        continue  # Skip fields we don't care about
                    
                    # Match metadata we care about
                    if any(p in key_lower for p in numeric_key_patterns):
                        if isinstance(value, (int, float)):
                            context_window = int(value)
                            logger.info(f"[GGUF Reader] Found context_window in '{key}': {context_window}")
                    elif key_lower == 'general.architecture':
                        architecture = str(value) if value else None
                        model_type = architecture
                        logger.info(f"[GGUF Reader] Found architecture: {architecture}")
                    elif key_lower == 'general.name':
                        model_name = str(value) if value else None
                        logger.info(f"[GGUF Reader] Found name: {model_name}")
                        
                except Exception as e:
                    logger.debug(f"[GGUF Reader] Error extracting field {key}: {e}")
                    continue
            
            if context_window or architecture or model_name:
                return HFModelMetadata(
                    context_window=context_window,
                    model_type=model_type,
                    architecture=architecture,
                    model_name=model_name,
                )
            
            logger.info("[GGUF Reader] No useful metadata found, trying manual parse")
            return self._parse_gguf_header_manual(file_path, original_filename)
            
        except ImportError:
            logger.info("[GGUF Reader] gguf library not available, using manual parse")
            return self._parse_gguf_header_manual(file_path, original_filename)
        except Exception as e:
            logger.info(f"[GGUF Reader] Failed ({e}), trying manual parse")
            return self._parse_gguf_header_manual(file_path, original_filename)
    
    def _parse_gguf_header_manual(self, file_path: str, original_filename: str) -> Optional[HFModelMetadata]:
        """Manual GGUF header parsing for truncated files.
        
        GGUF format:
        - Magic: 4 bytes ('GGUF')
        - Version: 4 bytes (uint32)
        - Tensor count: 8 bytes (uint64)
        - Metadata KV count: 8 bytes (uint64)
        - Metadata KV pairs: variable
        
        Each KV pair:
        - Key length: 8 bytes (uint64)
        - Key: variable (UTF-8 string)
        - Value type: 4 bytes (uint32)
        - Value: variable based on type
        """
        import struct
        
        try:
            with open(file_path, 'rb') as f:
                # Read header
                magic = f.read(4)
                if magic != b'GGUF':
                    return None
                
                version = struct.unpack('<I', f.read(4))[0]
                tensor_count = struct.unpack('<Q', f.read(8))[0]
                kv_count = struct.unpack('<Q', f.read(8))[0]
                
                logger.info(f"[GGUF Manual] Version: {version}, KV pairs: {kv_count}")
                
                context_window = None
                architecture = None
                
                # Parse KV pairs
                for _ in range(min(kv_count, 100)):  # Limit to prevent infinite loops
                    try:
                        # Read key
                        key_len = struct.unpack('<Q', f.read(8))[0]
                        if key_len > 1000:  # Sanity check
                            break
                        key = f.read(key_len).decode('utf-8')
                        
                        # Read value type
                        value_type = struct.unpack('<I', f.read(4))[0]
                        
                        # Parse value based on type
                        # Type 0 = uint8, 1 = int8, 2 = uint16, 3 = int16, 
                        # 4 = uint32, 5 = int32, 6 = float32, 7 = bool,
                        # 8 = string, 9 = array, 10 = uint64, 11 = int64, 12 = float64
                        
                        if value_type == 4:  # uint32
                            value = struct.unpack('<I', f.read(4))[0]
                        elif value_type == 5:  # int32
                            value = struct.unpack('<i', f.read(4))[0]
                        elif value_type == 10:  # uint64
                            value = struct.unpack('<Q', f.read(8))[0]
                        elif value_type == 8:  # string
                            str_len = struct.unpack('<Q', f.read(8))[0]
                            if str_len > 10000:  # Sanity check
                                break
                            value = f.read(str_len).decode('utf-8')
                        else:
                            # Skip other types for now
                            continue
                        
                        # Check for keys we care about
                        key_lower = key.lower()
                        if 'context_length' in key_lower or key_lower.endswith('.n_ctx'):
                            context_window = int(value)
                            logger.info(f"[GGUF Manual] Found context_window in '{key}': {context_window}")
                        elif key_lower == 'general.architecture':
                            architecture = str(value)
                            logger.info(f"[GGUF Manual] Found architecture: {architecture}")
                            
                    except struct.error:
                        # Hit end of data
                        break
                    except Exception as e:
                        logger.debug(f"[GGUF Manual] Error parsing KV: {e}")
                        break
                
                if context_window or architecture:
                    return HFModelMetadata(
                        context_window=context_window,
                        model_type=architecture,
                        architecture=architecture,
                    )
                
        except Exception as e:
            logger.warning(f"[GGUF Manual] Parse failed: {e}")
        
        # Try to infer from filename as last resort
        return self._infer_from_filename(original_filename)
    
    def _infer_from_filename(self, filename: str) -> Optional[HFModelMetadata]:
        """Last-resort inference from filename patterns."""
        import re
        
        filename_lower = filename.lower()
        
        # Try to extract context length from filename
        # Common patterns: "4k", "8k", "32k", "128k", "4K-instruct", etc.
        context_match = re.search(r'(\d+)k(?:-|_|\.|\b)', filename_lower)
        context_window = None
        if context_match:
            context_window = int(context_match.group(1)) * 1024
            logger.info(f"[GGUF Filename] Inferred context_window from filename: {context_window}")
        
        # Try to extract model type/architecture
        model_type = None
        known_archs = ['llama', 'phi', 'qwen', 'mistral', 'gemma', 'falcon', 'mpt', 'starcoder']
        for arch in known_archs:
            if arch in filename_lower:
                model_type = arch
                break
        
        if context_window or model_type:
            return HFModelMetadata(
                context_window=context_window,
                model_type=model_type,
                architecture=model_type,
            )
        
        return None


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

huggingface_service = HuggingFaceService()
