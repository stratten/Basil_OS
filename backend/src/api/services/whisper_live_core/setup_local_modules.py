"""
Setup script for initializing local diart and pyannote.audio modules.
This script adds the vendor directory to the Python path and sets environment variables
for the local modules to work correctly.
"""

import os
import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local_modules_setup")

class LocalModulesSetup:
    """
    Helper class to set up local modules for diart and pyannote.audio.
    """
    
    @staticmethod
    def setup_paths():
        """Set up paths for local modules."""
        configured_vendor_path = os.environ.get("PYANNOTE_VENDOR_PATH")
        vendor_path = Path(configured_vendor_path).expanduser() if configured_vendor_path else Path(__file__).resolve().parents[2] / "vendor"
        vendor_path = str(vendor_path)
        logger.info(f"Vendor path: {vendor_path}")
        if not os.path.exists(os.path.join(vendor_path, "models", "pyannote")):
            logger.warning(f"Could not find pyannote models in vendor path: {vendor_path}")
        
        # Set environment variables
        os.environ["PYANNOTE_DISABLE_HF_CHECKS"] = "1"
        
        # CRITICAL FIX: Ensure our vendor pyannote gets imported instead of system pyannote
        LocalModulesSetup._hijack_pyannote_imports(vendor_path)
        os.environ["PYANNOTE_VENDOR_PATH"] = vendor_path
        
        # Add vendor directory to Python path
        if vendor_path not in sys.path:
            logger.info(f"Adding vendor path to Python path: {vendor_path}")
            sys.path.insert(0, vendor_path)
        
        # Add diart package path to Python path
        diart_path = os.path.join(vendor_path, "diart", "diart-main", "src")
        if os.path.exists(diart_path) and diart_path not in sys.path:
            logger.info(f"Adding diart path to Python path: {diart_path}")
            sys.path.insert(0, diart_path)
        
        # Add pyannote.audio path to Python path
        pyannote_path = os.path.join(vendor_path, "pyannote")
        if os.path.exists(pyannote_path) and pyannote_path not in sys.path:
            logger.info(f"Adding pyannote path to Python path: {pyannote_path}")
            sys.path.insert(0, pyannote_path)
        
        return vendor_path
    
    @staticmethod
    def check_models():
        """Check if model files exist in the expected locations."""
        vendor_path = os.environ.get("PYANNOTE_VENDOR_PATH")
        if not vendor_path:
            vendor_path = LocalModulesSetup.setup_paths()
        
        models_dir = os.path.join(vendor_path, "models", "pyannote")
        
        if not os.path.exists(models_dir):
            logger.warning(f"Models directory not found: {models_dir}")
            return False
        
        required_models = {
            "segmentation": os.path.join(models_dir, "segmentation", "pytorch_model.bin"),
            "segmentation-3.0": os.path.join(models_dir, "segmentation-3.0", "pytorch_model.bin"),
            "embedding": os.path.join(models_dir, "embedding", "pytorch_model.bin")
        }
        
        missing_models = []
        for model_name, model_path in required_models.items():
            if not os.path.exists(model_path):
                missing_models.append(f"{model_name}: {model_path}")
        
        if missing_models:
            logger.warning("Some model files are missing:")
            for missing in missing_models:
                logger.warning(f"  - {missing}")
            return False
        
        logger.info("All required model files are present")
        return True
    
    @staticmethod
    def test_imports():
        """Test importing the local modules."""
        import_errors = []
        
        try:
            import pyannote.audio
            logger.info(f"Successfully imported pyannote.audio (version: {pyannote.audio.__version__})")
        except ImportError as e:
            import_errors.append(f"Failed to import pyannote.audio: {e}")
        
        try:
            import diart
            logger.info(f"Successfully imported diart")
        except ImportError as e:
            import_errors.append(f"Failed to import diart: {e}")
        
        if import_errors:
            for error in import_errors:
                logger.warning(error)
            return False
        
        return True
    
    @staticmethod
    def setup():
        """Run the complete setup and verification."""
        LocalModulesSetup.setup_paths()
        models_ok = LocalModulesSetup.check_models()
        imports_ok = LocalModulesSetup.test_imports()
        
        setup_ok = models_ok and imports_ok
        if setup_ok:
            logger.info("Local modules setup completed successfully")
        else:
            logger.warning("Local modules setup completed with issues")
        
        return setup_ok
    
    @staticmethod
    def _hijack_pyannote_imports(vendor_path):
        """
        Surgical fix: Ensure diart imports our local pyannote instead of system pyannote.
        This replaces system pyannote modules in sys.modules with our vendor versions.
        """
        # Add our vendor pyannote to the path FIRST
        pyannote_path = os.path.join(vendor_path, "pyannote")
        if pyannote_path not in sys.path:
            sys.path.insert(0, pyannote_path)
            logger.info(f"Inserted pyannote vendor path at front of sys.path: {pyannote_path}")
        
        # Remove any existing pyannote imports from sys.modules to force re-import from our vendor
        modules_to_remove = [name for name in sys.modules.keys() if name.startswith('pyannote.audio')]
        for module_name in modules_to_remove:
            del sys.modules[module_name]
            logger.debug(f"Removed existing module: {module_name}")
        
        if modules_to_remove:
            logger.info(f"Cleared {len(modules_to_remove)} existing pyannote.audio modules from sys.modules")
        
        # Pre-import critical pyannote modules from our vendor to establish them in sys.modules
        try:
            # Import key modules that diart will try to import
            import pyannote.audio
            import pyannote.audio.models
            import pyannote.audio.models.segmentation
            from pyannote.audio.models.segmentation import PyanNet
            logger.info("Pre-loaded vendor pyannote modules successfully")
        except Exception as e:
            logger.warning(f"Failed to pre-load some vendor pyannote modules: {e}")
            # Continue anyway, path manipulation should still work


# Run setup when this script is executed directly
if __name__ == "__main__":
    LocalModulesSetup.setup() 