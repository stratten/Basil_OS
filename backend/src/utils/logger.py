import logging
import sys
from typing import Optional

def setup_logger(name: str, level: Optional[int] = None, debug: bool = False) -> logging.Logger:
    """Set up a console logger with the specified name and level"""
    logger = logging.getLogger(name)
    
    if level is None:
        level = logging.DEBUG if debug else logging.INFO
    
    logger.setLevel(level)

    # Create console handler if not already present
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger 