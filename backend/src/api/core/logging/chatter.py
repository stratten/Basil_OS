"""A logger for per-item lines that bulk jobs repeat thousands of times, such as picking and loading a model for each memory summary.

The backend runs its main logger at DEBUG by default, so demoting a line to debug does not hide it.
These lines go through this child logger instead, which drops debug records unless `BASIL_VERBOSE_CHATTER=1` is set, so they do not drown out real startup errors.
Info, warning, and error records sent to it still reach the same handlers as the main logger.
"""

from __future__ import annotations

import logging
import os

from api.core.logging.api_logger import api_logger

VERBOSE_CHATTER_ENV = "BASIL_VERBOSE_CHATTER"

chatter_logger = api_logger.getChild("chatter")

if os.environ.get(VERBOSE_CHATTER_ENV, "").strip() == "1":
    # NOTSET defers to the main logger, which runs at DEBUG by default.
    chatter_logger.setLevel(logging.NOTSET)
else:
    chatter_logger.setLevel(logging.INFO)
