import sys
import os
import unittest
import platform
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.gpu_manager import GPUManager


class TestGPUManager(unittest.TestCase):
    """Tests for the GPUManager class."""
    
    def setUp(self):
        self.gpu_manager = GPUManager()
    
    def test_initialization(self):
        """Test that the GPUManager initializes correctly."""
        self.assertIsNotNone(self.gpu_manager.capabilities)
        self.assertIsInstance(self.gpu_manager.capabilities, dict)
        
        # Verify the capabilities dictionary has the expected keys
        expected_keys = ["available", "backend", "n_gpu_layers", "memory_optimizations"]
        for key in expected_keys:
            self.assertIn(key, self.gpu_manager.capabilities)
    
    def test_apple_silicon_detection(self):
        """Test Apple Silicon detection logic."""
        # This test can only verify the logic, not actual hardware
        is_darwin = platform.system() == "Darwin"
        is_arm64 = platform.machine() == "arm64"
        
        # The private method should match our direct check
        self.assertEqual(self.gpu_manager._is_apple_silicon(), is_darwin and is_arm64)
        
        # If we're on Apple Silicon, verify Metal is available
        if is_darwin and is_arm64:
            print("Testing on Apple Silicon hardware")
            self.assertTrue(self.gpu_manager.capabilities["available"])
            self.assertEqual(self.gpu_manager.capabilities["backend"], "metal")
            self.assertGreater(self.gpu_manager.capabilities["n_gpu_layers"], 0)
        else:
            print(f"Not testing on Apple Silicon: {platform.system()} {platform.machine()}")
    
    def test_model_config(self):
        """Test getting model-specific configurations."""
        # Test SOLAR model config
        solar_config = self.gpu_manager.get_model_config("solar")
        self.assertIsInstance(solar_config, dict)
        self.assertIn("n_gpu_layers", solar_config)
        
        # Test a large model with size-specific optimizations
        large_model_config = self.gpu_manager.get_model_config("llama", "70b")
        self.assertIsInstance(large_model_config, dict)
        self.assertIn("n_gpu_layers", large_model_config)
        
        # If on Apple Silicon, verify large model has appropriate layer reduction
        if self.gpu_manager.capabilities["available"] and self.gpu_manager.capabilities["backend"] == "metal":
            self.assertLessEqual(large_model_config["n_gpu_layers"], 30)
            

if __name__ == "__main__":
    unittest.main() 