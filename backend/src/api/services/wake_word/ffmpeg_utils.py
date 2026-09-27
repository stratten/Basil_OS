"""
FFmpeg executable discovery and bundle verification utilities.

This module handles finding the FFmpeg executable in various deployment scenarios:
- Bundled app (macOS .app bundle)
- PyInstaller bundle
- Development environment
- System FFmpeg fallback
"""

import os
import sys
import logging
import subprocess

# Use the exact same logger setup as other audio modules
from ...core.logging.api_logger import setup_api_logger
from ...core.config.api_settings import settings

logger = setup_api_logger(
    "api.main",
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)


def find_ffmpeg_executable():
    """
    Find the appropriate FFmpeg executable path.
    
    Returns:
        str: Path to FFmpeg executable (bundled or system)
    """
    logger.info("🔍 [FFMPEG_BUNDLE_VERIFICATION] Starting FFmpeg executable discovery...")
    
    # COMPREHENSIVE BUNDLE VERIFICATION DIAGNOSTICS
    _verify_ffmpeg_bundle_structure()
    
    # Check for bundled FFmpeg first (for packaged app)
    bundled_ffmpeg = _find_bundled_ffmpeg()
    if bundled_ffmpeg and os.path.isfile(bundled_ffmpeg) and os.access(bundled_ffmpeg, os.X_OK):
        logger.info(f"✅ Found bundled FFmpeg: {bundled_ffmpeg}")
        return bundled_ffmpeg
    
    # Fall back to system FFmpeg
    logger.info("🔍 No bundled FFmpeg found, using system FFmpeg")
    return "ffmpeg"  # Let ffmpeg-python find it in PATH


def _verify_ffmpeg_bundle_structure():
    """
    Comprehensive verification of FFmpeg bundle structure for debugging.
    This runs regardless of whether we're in a bundled app to help diagnose issues.
    """
    logger.info("📋 [FFMPEG_BUNDLE_VERIFICATION] === FFmpeg Bundle Structure Verification ===")
    
    # Get current execution context
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cwd = os.getcwd()
    
    logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] sys.executable: {sys.executable}")
    logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] Executable directory: {exe_dir}")
    logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] Current working directory: {cwd}")
    logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] PyInstaller bundle: {hasattr(sys, '_MEIPASS')}")
    if hasattr(sys, '_MEIPASS'):
        logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] _MEIPASS: {sys._MEIPASS}")
    
    # Check if we're in an app bundle
    in_app_bundle = 'Contents/MacOS' in exe_dir
    logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] In app bundle: {in_app_bundle}")
    
    if in_app_bundle:
        app_bundle_contents = os.path.dirname(exe_dir)  # Contents/
        app_bundle_resources = os.path.join(app_bundle_contents, 'Resources')
        backend_path = os.path.join(app_bundle_resources, 'backend')
        ffmpeg_bin_path = os.path.join(backend_path, 'bin')
        ffmpeg_exe_path = os.path.join(ffmpeg_bin_path, 'ffmpeg')
        ffmpeg_deps_path = os.path.join(backend_path, 'dependencies', 'libs')
        
        logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] App bundle structure analysis:")
        logger.info(f"  Contents directory: {app_bundle_contents} (exists: {os.path.exists(app_bundle_contents)})")
        logger.info(f"  Resources directory: {app_bundle_resources} (exists: {os.path.exists(app_bundle_resources)})")
        logger.info(f"  Backend directory: {backend_path} (exists: {os.path.exists(backend_path)})")
        logger.info(f"  FFmpeg bin directory: {ffmpeg_bin_path} (exists: {os.path.exists(ffmpeg_bin_path)})")
        logger.info(f"  FFmpeg executable: {ffmpeg_exe_path} (exists: {os.path.exists(ffmpeg_exe_path)})")
        logger.info(f"  FFmpeg deps directory: {ffmpeg_deps_path} (exists: {os.path.exists(ffmpeg_deps_path)})")
        
        # List contents of key directories
        if os.path.exists(backend_path):
            try:
                backend_contents = os.listdir(backend_path)
                logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] Backend directory contents: {backend_contents}")
            except Exception as e:
                logger.error(f"🚨 [FFMPEG_BUNDLE_VERIFICATION] Error listing backend directory: {e}")
        
        if os.path.exists(ffmpeg_bin_path):
            try:
                bin_contents = os.listdir(ffmpeg_bin_path)
                logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] Bin directory contents: {bin_contents}")
            except Exception as e:
                logger.error(f"🚨 [FFMPEG_BUNDLE_VERIFICATION] Error listing bin directory: {e}")
        
        if os.path.exists(ffmpeg_deps_path):
            try:
                deps_contents = os.listdir(ffmpeg_deps_path)
                logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] Dependencies directory contents: {deps_contents[:20]}...")  # Limit to first 20 items
            except Exception as e:
                logger.error(f"🚨 [FFMPEG_BUNDLE_VERIFICATION] Error listing dependencies directory: {e}")
        
        # Check FFmpeg executable properties
        if os.path.exists(ffmpeg_exe_path):
            try:
                import stat
                file_stat = os.stat(ffmpeg_exe_path)
                file_mode = stat.filemode(file_stat.st_mode)
                file_size = file_stat.st_size
                logger.info(f"🔍 [FFMPEG_BUNDLE_VERIFICATION] FFmpeg executable properties:")
                logger.info(f"  File mode: {file_mode}")
                logger.info(f"  File size: {file_size} bytes")
                logger.info(f"  Executable: {os.access(ffmpeg_exe_path, os.X_OK)}")
                logger.info(f"  Readable: {os.access(ffmpeg_exe_path, os.R_OK)}")
                
                # Try to get file type
                try:
                    result = subprocess.run(['file', ffmpeg_exe_path], 
                                          capture_output=True, text=True, timeout=5)
                    logger.info(f"  File type: {result.stdout.strip()}")
                except Exception as fe:
                    logger.info(f"  File type check failed: {fe}")
                    
            except Exception as e:
                logger.error(f"🚨 [FFMPEG_BUNDLE_VERIFICATION] Error checking FFmpeg executable properties: {e}")
    
    logger.info("📋 [FFMPEG_BUNDLE_VERIFICATION] === End FFmpeg Bundle Structure Verification ===")


def _find_bundled_ffmpeg():
    """
    Find the bundled FFmpeg executable.
    
    Returns:
        str: Path to bundled FFmpeg, or None if not found
    """
    # Possible bundled FFmpeg locations
    possible_locations = []
    
    # Check if we're in a bundled app (app bundle structure)
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller bundle
        possible_locations.append(os.path.join(sys._MEIPASS, 'bin', 'ffmpeg'))
    
    # Check for macOS app bundle structure
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    
    # If we're in a .app bundle (Contents/MacOS/), go up to Resources/backend/bin/ffmpeg
    if 'Contents/MacOS' in exe_dir:
        app_bundle_contents = os.path.dirname(exe_dir)  # Contents/
        app_bundle_resources = os.path.join(app_bundle_contents, 'Resources')
        possible_locations.append(os.path.join(app_bundle_resources, 'backend', 'bin', 'ffmpeg'))
    
    # Check relative to current working directory (for development)
    cwd = os.getcwd()
    possible_locations.extend([
        os.path.join(cwd, 'bin', 'ffmpeg'),
        os.path.join(cwd, 'backend', 'bin', 'ffmpeg'),
        os.path.join(cwd, '..', 'bin', 'ffmpeg'),
        './bin/ffmpeg',  # Relative to current directory
    ])
    
    # Check each possible location
    for location in possible_locations:
        if os.path.isfile(location) and os.access(location, os.X_OK):
            logger.info(f"🎯 Found bundled FFmpeg: {location}")
            return location
    
    logger.info("🔍 No bundled FFmpeg executable found")
    return None

