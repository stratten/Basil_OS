"""
Model scanning cache to avoid expensive filesystem operations on every startup
"""
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ModelScanCache:
    """Caches model scanning results to speed up startup"""
    
    def __init__(self, models_dir: Path, cache_file: Optional[Path] = None):
        self.models_dir = Path(models_dir)
        self.cache_file = cache_file or self.models_dir / ".model_scan_cache.json"
        self.cache_ttl = 3600  # 1 hour cache TTL
        
    def _get_directory_hash(self) -> str:
        """Get a hash of the models directory structure for cache invalidation"""
        if not self.models_dir.exists():
            return "empty"
            
        # Get modification times of all model files
        model_files = []
        for ext in ['*.gguf', '*.bin', '*.safetensors', '*.pt', '*.pth']:
            model_files.extend(self.models_dir.rglob(ext))
            
        # Create hash from file paths and modification times
        hash_input = ""
        for file_path in sorted(model_files):
            try:
                stat = file_path.stat()
                hash_input += f"{file_path}:{stat.st_mtime}:{stat.st_size}"
            except (OSError, FileNotFoundError):
                continue
                
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def get_cached_scan(self) -> Optional[Dict]:
        """Get cached scan results if valid"""
        try:
            if not self.cache_file.exists():
                return None
                
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
                
            # Check if cache is still valid
            cache_time = cache_data.get('timestamp', 0)
            cache_hash = cache_data.get('directory_hash', '')
            current_hash = self._get_directory_hash()
            
            if (time.time() - cache_time < self.cache_ttl and 
                cache_hash == current_hash):
                logger.info(f"✅ Using cached model scan (age: {time.time() - cache_time:.1f}s)")
                return cache_data.get('models', {})
            else:
                logger.info("🔄 Model cache expired or directory changed, will rescan")
                return None
                
        except Exception as e:
            logger.warning(f"⚠️ Error reading model cache: {e}")
            return None
    
    def save_scan_results(self, models: Dict):
        """Save scan results to cache"""
        try:
            cache_data = {
                'timestamp': time.time(),
                'directory_hash': self._get_directory_hash(),
                'models': models
            }
            
            # Ensure cache directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
            logger.info(f"💾 Saved model scan cache to {self.cache_file}")
            
        except Exception as e:
            logger.warning(f"⚠️ Error saving model cache: {e}")
    
    def clear_cache(self):
        """Clear the model scan cache"""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                logger.info("🗑️ Model scan cache cleared")
        except Exception as e:
            logger.warning(f"⚠️ Error clearing cache: {e}")
