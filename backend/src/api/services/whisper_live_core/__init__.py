# ===== BASIL CUSTOM: Initialize local module paths FIRST =====
import os
import sys

# Add this directory to sys.path so "whisperlivekit" imports work
# (Upstream code imports "from whisperlivekit.X" but we renamed dir to "whisper_live_core")
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Create an alias so "import whisperlivekit" finds this module
if 'whisperlivekit' not in sys.modules:
    sys.modules['whisperlivekit'] = sys.modules[__name__]

from .setup_local_modules import LocalModulesSetup
LocalModulesSetup.setup_paths()
# ===== END BASIL CUSTOM =====

from .audio_processor import AudioProcessor
from .core import TranscriptionEngine

__all__ = [
    "TranscriptionEngine",
    "AudioProcessor",
    "LocalModulesSetup",
]
