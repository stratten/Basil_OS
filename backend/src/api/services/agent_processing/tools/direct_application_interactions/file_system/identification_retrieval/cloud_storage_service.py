"""
Cloud Storage Service

Handles integration with cloud storage services like Google Drive, OneDrive, Dropbox.
Extends file system operations to include cloud-mounted volumes and API access.
"""

import asyncio
import glob
import logging
import subprocess
import os
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from .search_subprocess import run_bounded_search_process

logger = logging.getLogger(__name__)

_FIND_TIMEOUT_SECONDS = 30.0
_PERMISSION_ONLY_STDERR_MARKERS = ("Permission denied", "Operation not permitted")


class CloudStorageService:
    """
    Service for detecting and accessing cloud storage integrations.
    
    Handles:
    - Google Drive (mounted volumes and API)
    - OneDrive (mounted volumes)
    - Dropbox (mounted volumes)
    - iCloud Drive (local sync folders)
    """
    
    def __init__(self):
        self.detected_volumes = {}
        self.cloud_providers = {
            'google_drive': {
                'volume_patterns': ['GoogleDrive', 'Google Drive'],
                # Modern Google Drive for Desktop mounts per-account under
                # ~/Library/CloudStorage/GoogleDrive-<email>. The account dir is a
                # glob because the email varies; legacy paths are kept as a fallback.
                'sync_paths': [
                    '~/Google Drive',
                    '~/GoogleDrive',
                    '~/Library/CloudStorage/GoogleDrive-*',
                ],
                'api_available': False
            },
            'onedrive': {
                'volume_patterns': ['OneDrive'],
                'sync_paths': [
                    '~/OneDrive',
                    '~/OneDrive - Personal',
                    '~/Library/CloudStorage/OneDrive-*',
                ],
                'api_available': False
            },
            'dropbox': {
                'volume_patterns': ['Dropbox'],
                'sync_paths': ['~/Dropbox'],
                'api_available': False
            },
            'icloud': {
                'volume_patterns': [],  # iCloud doesn't mount as volume
                'sync_paths': ['~/Library/Mobile Documents/com~apple~CloudDocs'],
                'api_available': False
            }
        }
    
    async def detect_cloud_storage(self) -> Dict[str, Any]:
        """
        Detect all available cloud storage integrations.
        
        Returns:
            Dictionary with detected cloud storage information
        """
        logger.info("🔍 Detecting cloud storage integrations...")
        
        detection_results = {
            'volumes_detected': {},
            'sync_folders_detected': {},
            'total_providers': 0,
            'searchable_paths': []
        }
        
        try:
            # Detect mounted volumes
            volumes = await self._detect_mounted_volumes()
            detection_results['volumes_detected'] = volumes
            
            # Detect sync folders
            sync_folders = await self._detect_sync_folders()
            detection_results['sync_folders_detected'] = sync_folders
            
            # Combine all searchable paths
            all_paths = []
            for provider_volumes in volumes.values():
                all_paths.extend(provider_volumes)
            for provider_folders in sync_folders.values():
                all_paths.extend(provider_folders)
            
            detection_results['searchable_paths'] = all_paths
            detection_results['total_providers'] = len([p for p in self.cloud_providers.keys() 
                                                       if p in volumes or p in sync_folders])
            
            logger.info(f"✅ Cloud storage detection complete: {detection_results['total_providers']} providers")
            return detection_results
            
        except Exception as e:
            logger.error(f"❌ Error detecting cloud storage: {e}", exc_info=True)
            return detection_results
    
    async def _detect_mounted_volumes(self) -> Dict[str, List[str]]:
        """Detect cloud storage mounted as volumes."""
        logger.info("🗂️  Detecting mounted cloud volumes...")
        
        volumes = {}
        
        try:
            # Get all mounted volumes
            result = await asyncio.to_thread(
                subprocess.run, ['df', '-h'], capture_output=True, text=True, timeout=10
            )
            mounted_paths = []
            
            for line in result.stdout.split('\n')[1:]:  # Skip header
                if line.strip() and '/Volumes/' in line:
                    parts = line.split()
                    if len(parts) >= 6:
                        mount_point = ' '.join(parts[5:])  # Handle spaces in names
                        mounted_paths.append(mount_point)
            
            # Check each provider's volume patterns
            for provider, config in self.cloud_providers.items():
                provider_volumes = []
                
                for pattern in config['volume_patterns']:
                    for mount_point in mounted_paths:
                        if pattern.lower() in mount_point.lower():
                            if os.path.exists(mount_point) and os.access(mount_point, os.R_OK):
                                provider_volumes.append(mount_point)
                                logger.info(f"   ✅ Found {provider} volume: {mount_point}")
                
                if provider_volumes:
                    volumes[provider] = provider_volumes
            
            return volumes
            
        except Exception as e:
            logger.error(f"❌ Error detecting mounted volumes: {e}")
            return {}
    
    async def _detect_sync_folders(self) -> Dict[str, List[str]]:
        """Detect cloud storage sync folders."""
        logger.info("📁 Detecting cloud sync folders...")
        
        sync_folders = {}
        
        try:
            for provider, config in self.cloud_providers.items():
                provider_folders = []
                
                for sync_path in config['sync_paths']:
                    # Wildcard sync paths (e.g. CloudStorage per-account dirs) expand
                    # to zero or more concrete directories; plain paths expand to one.
                    if any(token in sync_path for token in ('*', '?', '[')):
                        expanded_candidates = sorted(glob.glob(os.path.expanduser(sync_path)))
                    else:
                        expanded_candidates = [os.path.expanduser(sync_path)]

                    for expanded_path in expanded_candidates:
                        if os.path.exists(expanded_path) and os.path.isdir(expanded_path):
                            # Check if it's actually a sync folder (contains files)
                            try:
                                contents = os.listdir(expanded_path)
                                if contents:  # Not empty
                                    provider_folders.append(expanded_path)
                                    logger.info(f"   ✅ Found {provider} sync folder: {expanded_path}")
                            except PermissionError:
                                logger.debug(f"   ⚠️ Permission denied for {expanded_path}")
                
                if provider_folders:
                    sync_folders[provider] = provider_folders
            
            return sync_folders
            
        except Exception as e:
            logger.error(f"❌ Error detecting sync folders: {e}")
            return {}
    
    async def search_cloud_files(self, filename: str, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for files across cloud storage and return only the files found."""
        coverage = await self.search_cloud_files_with_coverage(filename, provider)
        return coverage["files"]

    async def search_cloud_files_with_coverage(
        self, filename: str, provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for files across cloud storage using file system access.
        
        Args:
            filename: Name of file to search for
            provider: Optional specific provider to search (google_drive, onedrive, etc.)
            
        Returns:
            {"files": [...], "incomplete_paths": [{"path": ..., "reason": ...}]}; a path is incomplete when its find timed out, failed, or errored, so empty files plus incomplete paths is not evidence that a file does not exist.
        """
        logger.info(f"🔍 Searching cloud files for: '{filename}' (provider: {provider or 'all'})")
        
        # First detect available cloud storage
        detection = await self.detect_cloud_storage()
        searchable_paths = detection['searchable_paths']
        
        if not searchable_paths:
            logger.warning("⚠️ No cloud storage paths found to search")
            return {"files": [], "incomplete_paths": []}
        
        # Filter paths by provider if specified
        if provider:
            filtered_paths = []
            volumes = detection['volumes_detected'].get(provider, [])
            sync_folders = detection['sync_folders_detected'].get(provider, [])
            filtered_paths.extend(volumes)
            filtered_paths.extend(sync_folders)
            searchable_paths = filtered_paths
        
        # Search in each path
        found_files = []
        incomplete_paths: List[Dict[str, str]] = []
        for search_path in searchable_paths:
            try:
                files, incomplete_reason = await self._search_in_path_with_coverage(search_path, filename)
            except Exception as e:
                logger.debug(f"⚠️ Error searching in {search_path}: {e}")
                incomplete_paths.append({"path": search_path, "reason": f"search error: {e}"})
                continue
            for file_info in files:
                file_info['cloud_provider'] = self._identify_provider(search_path)
                file_info['is_cloud_file'] = True
            found_files.extend(files)
            if incomplete_reason:
                incomplete_paths.append({"path": search_path, "reason": incomplete_reason})
        
        logger.info(f"✅ Found {len(found_files)} cloud files ({len(incomplete_paths)} incomplete path(s))")
        return {"files": found_files, "incomplete_paths": incomplete_paths}
    
    async def _search_in_path(self, search_path: str, filename: str) -> List[Dict[str, Any]]:
        """Search for files in a specific path using find command."""
        files, _incomplete_reason = await self._search_in_path_with_coverage(search_path, filename)
        return files

    async def _search_in_path_with_coverage(
        self, search_path: str, filename: str
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Search one path with find, keeping partial results and reporting why coverage is incomplete."""
        incomplete_reason: Optional[str] = None
        try:
            # Case-insensitive find that prunes hidden directories EXCEPT
            # Google Drive's `.shortcut-targets-by-id` subtree, where "Shared with
            # me" targets live. A blanket `-not -path '*/.*'` would skip them.
            cmd = [
                'find', search_path,
                '-type', 'd', '-name', '.*', '-not', '-name', '.shortcut-targets-by-id', '-prune',
                '-o',
                '-type', 'f', '-iname', f'*{filename}*', '-print',
            ]
            
            outcome = await run_bounded_search_process(cmd, timeout_seconds=_FIND_TIMEOUT_SECONDS)
            
            if outcome.timed_out:
                logger.warning(
                    f"⏰ Search timed out in {search_path}; keeping {len(outcome.lines)} partial result(s)"
                )
                incomplete_reason = f"timed out after {_FIND_TIMEOUT_SECONDS:.0f}s"
            
            if outcome.returncode not in (0, None) and not outcome.timed_out:
                stderr_lines = [line for line in outcome.stderr_tail.splitlines() if line.strip()]
                permission_only = bool(stderr_lines) and all(
                    any(marker in line for marker in _PERMISSION_ONLY_STDERR_MARKERS)
                    for line in stderr_lines
                )
                logger.debug(f"Find exited {outcome.returncode} for {search_path}: {outcome.stderr_tail[-500:]}")
                if not permission_only:
                    incomplete_reason = f"find exited with status {outcome.returncode}"
            
            file_paths = [path for path in outcome.lines if path]
            total_found = len(file_paths)
            
            # Get metadata for each file
            files = []
            for file_path in file_paths[:20]:  # Limit to 20 results per path
                try:
                    stat = os.stat(file_path)
                    files.append({
                        'name': os.path.basename(file_path),
                        'path': file_path,
                        'size': stat.st_size,
                        'modified_date': stat.st_mtime,
                        'is_readable': os.access(file_path, os.R_OK),
                        'discovery_total_found': total_found,
                        'discovery_returned_count': min(total_found, 20),
                        'discovery_has_more': total_found > 20,
                    })
                except Exception as e:
                    logger.debug(f"⚠️ Could not get metadata for {file_path}: {e}")
            
            return files, incomplete_reason
            
        except Exception as e:
            logger.error(f"❌ Error searching in {search_path}: {e}")
            return [], f"search error: {e}"
    
    def _identify_provider(self, path: str) -> str:
        """Identify which cloud provider a path belongs to."""
        path_lower = path.lower()
        
        if 'google' in path_lower or 'googledrive' in path_lower:
            return 'google_drive'
        elif 'onedrive' in path_lower:
            return 'onedrive'
        elif 'dropbox' in path_lower:
            return 'dropbox'
        elif 'icloud' in path_lower or 'mobile documents' in path_lower:
            return 'icloud'
        else:
            return 'unknown'
    
    async def can_access_file(self, file_path: str) -> bool:
        """Check if a cloud file can be accessed (not just a placeholder)."""
        try:
            # Check if file exists and is readable
            if not os.path.exists(file_path) or not os.access(file_path, os.R_OK):
                return False
            
            # For cloud files, try to read a small amount to ensure it's not a placeholder
            try:
                with open(file_path, 'rb') as f:
                    f.read(1024)  # Try to read first 1KB
                return True
            except (OSError, IOError):
                logger.debug(f"⚠️ File appears to be placeholder: {file_path}")
                return False
                
        except Exception as e:
            logger.debug(f"⚠️ Cannot access file {file_path}: {e}")
            return False
    
    def get_service_capabilities(self) -> Dict[str, Any]:
        """Get cloud storage service capabilities."""
        return {
            "description": "Cloud storage integration for Google Drive, OneDrive, Dropbox, and iCloud",
            "supported_providers": list(self.cloud_providers.keys()),
            "detection_methods": [
                "Mounted volume detection",
                "Sync folder discovery", 
                "File system search with find command",
                "Provider-specific path patterns"
            ],
            "limitations": [
                "Placeholder files may not be accessible",
                "API access requires authentication setup",
                "Search performance depends on cloud sync status",
                "Some providers require special permissions"
            ],
            "methods": {
                "detect_cloud_storage": "Scan for all available cloud storage",
                "search_cloud_files": "Search files across cloud providers",
                "can_access_file": "Verify file accessibility (not placeholder)"
            }
        } 