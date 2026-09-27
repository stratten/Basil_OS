"""In-memory state for meeting route workflows."""

from typing import Any, Dict


# Track active post-processing jobs
active_post_processing: Dict[str, Any] = {}

# Track active analysis jobs
active_analysis: Dict[str, Any] = {}
