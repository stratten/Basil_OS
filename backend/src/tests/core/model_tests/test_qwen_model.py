#!/usr/bin/env python3
"""
Qwen Model Direct Test Tool

This script tests the Qwen model implementation in isolation,
without going through the complex activity processing pipeline.
"""

import os
import sys
import asyncio
import logging
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Add the Basil directory to the Python path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up to the main Basil directory and add src to path
BASIL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
SRC_PATH = os.path.join(BASIL_ROOT, "src")
sys.path.insert(0, SRC_PATH)

# Import the Qwen model and required types
from api.core.models.reasoning.qwen_model import QwenModel
from api.core.models.model_types import ModelCapability
from api.core.models.base_model import ModelState

class QwenModelTester:
    """Comprehensive tester for the Qwen model"""
    
    def __init__(self):
        self.model_path = Path(os.path.expanduser("~/.basil/models/qwen3-4b-base"))
        self.model = None
        self.test_results = {}
        
    def log_test_result(self, test_name: str, success: bool, details: str = ""):
        """Log and store test results"""
        status = "✅ PASS" if success else "❌ FAIL"
        self.test_results[test_name] = {"success": success, "details": details}
        logging.info(f"{status} {test_name}: {details}")
        
    async def test_model_path_exists(self):
        """Test 1: Check if model path exists"""
        logging.info("=== Test 1: Model Path Verification ===")
        
        exists = self.model_path.exists()
        is_dir = self.model_path.is_dir()
        
        if exists and is_dir:
            # List model files
            files = list(self.model_path.glob("*"))
            file_count = len(files)
            file_list = [f.name for f in files[:5]]  # First 5 files
            
            self.log_test_result(
                "model_path_exists", 
                True, 
                f"Found {file_count} files: {file_list}..."
            )
            return True
        else:
            self.log_test_result(
                "model_path_exists", 
                False, 
                f"Path exists: {exists}, is_dir: {is_dir}"
            )
            return False
    
    async def test_model_creation(self):
        """Test 2: Create QwenModel instance"""
        logging.info("=== Test 2: Model Instance Creation ===")
        
        try:
            self.model = QwenModel(
                model_path=self.model_path,
                required_capabilities={ModelCapability.REASONING}
            )
            
            # Check initial state
            initial_state = self.model.state
            is_loaded = self.model.is_loaded
            
            self.log_test_result(
                "model_creation", 
                True, 
                f"State: {initial_state}, is_loaded: {is_loaded}"
            )
            return True
            
        except Exception as e:
            self.log_test_result(
                "model_creation", 
                False, 
                f"Exception: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_model_loading(self):
        """Test 3: Load the model"""
        if not self.model:
            self.log_test_result("model_loading", False, "No model instance")
            return False
            
        logging.info("=== Test 3: Model Loading ===")
        
        try:
            start_time = time.time()
            
            # Load the model
            await self.model.load()
            
            loading_time = time.time() - start_time
            
            # Check post-loading state
            final_state = self.model.state
            is_loaded = self.model.is_loaded
            
            if final_state == ModelState.READY and is_loaded:
                self.log_test_result(
                    "model_loading", 
                    True, 
                    f"Loaded in {loading_time:.2f}s, state: {final_state}"
                )
                
                # Log loading method used
                loading_method = "Direct MPS" if hasattr(self.model, '_device') and "mps" in str(self.model._device) else "Standard"
                logging.info(f"Loading method: {loading_method}")
                
                return True
            else:
                self.log_test_result(
                    "model_loading", 
                    False, 
                    f"State: {final_state}, is_loaded: {is_loaded}"
                )
                return False
                
        except Exception as e:
            loading_time = time.time() - start_time
            self.log_test_result(
                "model_loading", 
                False, 
                f"Exception after {loading_time:.2f}s: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_model_metadata(self):
        """Test 4: Get model metadata (test Pydantic validation fix)"""
        if not self.model or not self.model.is_loaded:
            self.log_test_result("model_metadata", False, "Model not loaded")
            return False
            
        logging.info("=== Test 4: Model Metadata (Pydantic Validation) ===")
        
        try:
            metadata = self.model.get_metadata()
            
            # Check metadata fields
            has_name = hasattr(metadata, 'name') and metadata.name
            has_description = hasattr(metadata, 'description') and metadata.description
            has_capabilities = hasattr(metadata, 'capabilities') and metadata.capabilities
            has_parameters = hasattr(metadata, 'parameters') and isinstance(metadata.parameters, dict)
            
            details = f"Name: {metadata.name}, Capabilities: {len(metadata.capabilities)}, Parameters: {type(metadata.parameters).__name__}"
            
            if has_name and has_description and has_capabilities and has_parameters:
                self.log_test_result("model_metadata", True, details)
                
                # Log parameter details
                if metadata.parameters:
                    param_keys = list(metadata.parameters.keys())[:3]
                    logging.info(f"Parameter keys: {param_keys}...")
                
                return True
            else:
                missing = []
                if not has_name: missing.append("name")
                if not has_description: missing.append("description") 
                if not has_capabilities: missing.append("capabilities")
                if not has_parameters: missing.append("parameters")
                
                self.log_test_result("model_metadata", False, f"Missing: {missing}")
                return False
                
        except Exception as e:
            self.log_test_result(
                "model_metadata", 
                False, 
                f"Exception: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_simple_generation(self):
        """Test 5: Simple text generation"""
        if not self.model or not self.model.is_loaded:
            self.log_test_result("simple_generation", False, "Model not loaded")
            return False
            
        logging.info("=== Test 5: Simple Text Generation ===")
        
        try:
            # Use a very simple math prompt
            test_prompt = "What is 2 + 2? Just give me the number."
            
            start_time = time.time()
            
            response = await self.model.generate_response(
                prompt=test_prompt,
                max_tokens=10,
                temperature=0.0  # Deterministic
            )
            
            generation_time = time.time() - start_time
            
            if response and len(response.strip()) > 0:
                self.log_test_result(
                    "simple_generation", 
                    True, 
                    f"Generated '{response.strip()}' in {generation_time:.2f}s"
                )
                return True
            else:
                self.log_test_result(
                    "simple_generation", 
                    False, 
                    f"Empty response after {generation_time:.2f}s"
                )
                return False
                
        except Exception as e:
            generation_time = time.time() - start_time
            self.log_test_result(
                "simple_generation", 
                False, 
                f"Exception after {generation_time:.2f}s: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_complex_generation(self):
        """Test 6: More complex text generation"""
        if not self.model or not self.model.is_loaded:
            self.log_test_result("complex_generation", False, "Model not loaded")
            return False
            
        logging.info("=== Test 6: Complex Text Generation ===")
        
        try:
            # Use a more complex prompt similar to activity processing
            test_prompt = """Analyze this screenshot content and provide insights:

Screen Text: "Microsoft Outlook - Inbox - 3 new messages about project updates"
App: Microsoft Outlook  
Time: 2025-01-08 22:42:00

Please provide a brief analysis of what the user is doing."""
            
            start_time = time.time()
            
            response = await self.model.generate_response(
                prompt=test_prompt,
                max_tokens=100,
                temperature=0.3
            )
            
            generation_time = time.time() - start_time
            
            if response and len(response.strip()) > 20:  # Expect longer response
                self.log_test_result(
                    "complex_generation", 
                    True, 
                    f"Generated {len(response)} chars in {generation_time:.2f}s"
                )
                logging.info(f"Response preview: {response[:100]}...")
                return True
            else:
                self.log_test_result(
                    "complex_generation", 
                    False, 
                    f"Response too short ({len(response) if response else 0} chars) after {generation_time:.2f}s"
                )
                return False
                
        except Exception as e:
            generation_time = time.time() - start_time
            self.log_test_result(
                "complex_generation", 
                False, 
                f"Exception after {generation_time:.2f}s: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_model_persistence(self):
        """Test 7: Model persistence (multiple loads)"""
        if not self.model:
            self.log_test_result("model_persistence", False, "No model instance")
            return False
            
        logging.info("=== Test 7: Model Persistence ===")
        
        try:
            # Test multiple load calls
            first_load_time = time.time()
            await self.model.load()
            first_duration = time.time() - first_load_time
            
            second_load_time = time.time()
            await self.model.load()  # Should be instant due to caching
            second_duration = time.time() - second_load_time
            
            # Second load should be much faster (cached)
            is_cached = second_duration < (first_duration * 0.1)  # 10x faster threshold
            
            self.log_test_result(
                "model_persistence", 
                True, 
                f"1st load: {first_duration:.2f}s, 2nd load: {second_duration:.2f}s, cached: {is_cached}"
            )
            return True
            
        except Exception as e:
            self.log_test_result(
                "model_persistence", 
                False, 
                f"Exception: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def test_model_unloading(self):
        """Test 8: Model unloading"""
        if not self.model:
            self.log_test_result("model_unloading", False, "No model instance")
            return False
            
        logging.info("=== Test 8: Model Unloading ===")
        
        try:
            # Unload the model
            await self.model.unload()
            
            # Check post-unloading state
            final_state = self.model.state
            is_loaded = self.model.is_loaded
            
            if final_state != ModelState.READY and not is_loaded:
                self.log_test_result(
                    "model_unloading", 
                    True, 
                    f"State: {final_state}, is_loaded: {is_loaded}"
                )
                return True
            else:
                self.log_test_result(
                    "model_unloading", 
                    False, 
                    f"Still loaded - State: {final_state}, is_loaded: {is_loaded}"
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "model_unloading", 
                False, 
                f"Exception: {type(e).__name__}: {str(e)}"
            )
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        logging.info("🧪 Starting Qwen Model Comprehensive Test Suite")
        logging.info("=" * 80)
        
        # Run tests in order
        tests = [
            self.test_model_path_exists,
            self.test_model_creation, 
            self.test_model_loading,
            self.test_model_metadata,
            self.test_simple_generation,
            self.test_complex_generation,
            self.test_model_persistence,
            self.test_model_unloading
        ]
        
        results = []
        for test in tests:
            try:
                result = await test()
                results.append(result)
            except Exception as e:
                logging.error(f"Test {test.__name__} crashed: {e}")
                results.append(False)
        
        # Print summary
        logging.info("=" * 80)
        logging.info("📊 TEST RESULTS SUMMARY")
        logging.info("=" * 80)
        
        passed = sum(results)
        total = len(results)
        
        for test_name, result_data in self.test_results.items():
            status = "✅" if result_data["success"] else "❌"
            details = result_data["details"]
            logging.info(f"{status} {test_name}: {details}")
        
        logging.info("-" * 80)
        logging.info(f"📈 OVERALL: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        
        if passed == total:
            logging.info("🎉 ALL TESTS PASSED! Qwen model is working correctly.")
        elif passed >= total * 0.8:
            logging.info("⚠️  Most tests passed, but some issues remain.")
        else:
            logging.info("❌ Multiple test failures - Qwen model needs attention.")
        
        # Recommendations
        logging.info("=" * 80)
        logging.info("💡 RECOMMENDATIONS")
        logging.info("=" * 80)
        
        if not self.test_results.get("model_path_exists", {}).get("success"):
            logging.info("📁 Download the Qwen3-4B model to ~/.basil/models/qwen3-4b-base")
        
        if not self.test_results.get("model_loading", {}).get("success"):
            logging.info("🔧 Check transformers version and MPS availability")
        
        if not self.test_results.get("model_metadata", {}).get("success"):
            logging.info("🔍 Investigate Pydantic validation issues in get_metadata()")
        
        if not self.test_results.get("simple_generation", {}).get("success"):
            logging.info("⚡ Check text generation pipeline and device settings")
        
        logging.info("=" * 80)
        
        return passed == total

async def main():
    """Main test runner"""
    tester = QwenModelTester()
    success = await tester.run_all_tests()
    
    # Exit with appropriate code
    logging.info(f"🏁 Test suite completed. Exit code: {0 if success else 1}")
    return success

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 