"""GPU capability detection and configuration for AI models."""

import platform
import os
import subprocess
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class GPUManager:
    """Manages GPU detection and configuration for AI models."""
    
    def __init__(self):
        """Initialize the GPU manager."""
        self.capabilities = self.detect_gpu_capabilities()
        logger.info(f"Initialized GPU manager with capabilities: {self.capabilities}")
        
    def detect_gpu_capabilities(self) -> Dict[str, Any]:
        """Detect available GPU capabilities on the current system.
        
        Returns:
            Dictionary with GPU capabilities and recommended configurations.
        """
        gpu_capabilities = {
            "available": False,
            "backend": None,
            "n_gpu_layers": 0,
            "memory_optimizations": {}
        }
        
        # Check for Apple Silicon (arm64 macOS)
        if self._is_apple_silicon():
            gpu_capabilities = self._get_metal_capabilities()
            
        # Future platform checks would go here (CUDA, ROCm, DirectML, etc.)
        
        # Log detection results
        if gpu_capabilities["available"]:
            logger.info(f"GPU acceleration available: {gpu_capabilities['backend']}")
            logger.info(f"Recommended GPU layers: {gpu_capabilities['n_gpu_layers']}")
        else:
            logger.info("No GPU acceleration available, using CPU only")
            
        return gpu_capabilities
    
    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        is_apple = platform.system() == "Darwin" and platform.machine() == "arm64"
        logger.info(f"Apple Silicon detection: {is_apple} (system={platform.system()}, machine={platform.machine()})")
        return is_apple
    
    def _get_metal_capabilities(self) -> Dict[str, Any]:
        """Get Metal-specific capabilities for Apple Silicon.
        
        Returns:
            Dictionary with Metal-specific capabilities.
        """
        capabilities = {
            "available": False,
            "backend": "metal",
            "n_gpu_layers": 0,
            "memory_optimizations": {}
        }
        
        try:
            # Check if Metal is available
            # This is a simple check - ideally we would check more thoroughly
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], 
                capture_output=True, 
                text=True, 
                check=True
            )
            
            # Convert bytes to GB
            total_memory = int(result.stdout.strip()) / (1024**3)
            
            # Metal is available on Apple Silicon by default
            capabilities["available"] = True
            logger.info(f"Metal acceleration is available on this Apple Silicon Mac")
            
            # Configure based on available memory
            # These are reasonable defaults based on testing with SOLAR/Llama models
            if total_memory >= 32:  # 32GB or more RAM
                capabilities["n_gpu_layers"] = 43  # Nearly all layers
                capabilities["memory_optimizations"] = {"f16_kv": True}
            elif total_memory >= 16:  # 16GB RAM (most M1/M2 Macs)
                capabilities["n_gpu_layers"] = 32  # Most layers
                capabilities["memory_optimizations"] = {"f16_kv": True}
            else:  # 8GB RAM (base models)
                capabilities["n_gpu_layers"] = 24  # Fewer layers to avoid OOM
                capabilities["memory_optimizations"] = {
                    "f16_kv": True,
                    "compress_pos_emb": 16  # Compress position embeddings to save memory
                }
                
            logger.info(f"Detected {total_memory:.1f}GB RAM on Apple Silicon")
            logger.info(f"Configured Metal acceleration with {capabilities['n_gpu_layers']} GPU layers")
            
        except (subprocess.SubprocessError, ValueError) as e:
            logger.warning(f"Error detecting Metal capabilities: {e}")
            # Fall back to CPU mode
            
        return capabilities
        
    def get_model_config(self, model_type: str, model_size: Optional[str] = None) -> Dict[str, Any]:
        """Get recommended configuration for a specific model.
        
        This allows for model-specific optimizations beyond the general
        platform capabilities.
        
        Args:
            model_type: Type of model (e.g., "solar", "llama", "phi")
            model_size: Optional size qualifier (e.g., "7b", "13b")
            
        Returns:
            Dictionary with recommended configuration for the model.
        """
        config = {
            "n_gpu_layers": self.capabilities["n_gpu_layers"],
            "available": self.capabilities["available"],
            "backend": self.capabilities["backend"],
            "memory_optimizations": self.capabilities["memory_optimizations"]
        }
        
        # Model-specific adjustments
        if model_type == "solar":
            # SOLAR models are optimized for efficiency
            logger.info(f"Configuring SOLAR model with {config['n_gpu_layers']} GPU layers")
            # Add any SOLAR-specific optimizations here
        elif model_type == "qwen3-4b":
            # Qwen3-4B models are optimized for Apple Silicon and efficiency
            logger.info(f"Configuring Qwen3-4B model with {config['n_gpu_layers']} GPU layers")
            # Qwen3-4B works well with MPS acceleration on Apple Silicon
            if config["backend"] == "metal":
                config["memory_optimizations"]["use_mps"] = True
        elif model_type == "llama" and model_size == "70b":
            # Reduce layers for very large models
            config["n_gpu_layers"] = min(config["n_gpu_layers"], 30)
            logger.info(f"Adjusted large Llama model to use {config['n_gpu_layers']} GPU layers")
            
        return config 