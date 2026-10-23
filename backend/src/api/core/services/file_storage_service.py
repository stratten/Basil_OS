"""Service for managing file storage and paths."""

import sys
import platform
from datetime import datetime
from pathlib import Path
import shutil
import logging

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, development_mode: bool = True) -> None:
        """Initialize storage service.

        Args:
            development_mode: If True, uses development paths
        """
        self.development_mode = development_mode
        self.base_path = self._get_base_path()
        self._initialize_directories()

    def _get_base_path(self) -> Path:
        """Get appropriate base path for current platform and mode."""
        if self.development_mode:
            return Path.home() / ".basil"

        system = platform.system()

        if system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / "Basil"
        elif system == "Windows":
            return Path.home() / "AppData" / "Local" / "Basil"
        else:  # Linux and others
            return Path.home() / ".local" / "share" / "basil"

    def _initialize_directories(self) -> None:
        """Create required directory structure."""
        dirs = [
            self.base_path / "data" / "captures",
            self.base_path / "data" / "processed",
            self.base_path / "data" / "temp",
        ]

        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized storage at: {self.base_path}")

    def get_db_path(self) -> Path:
        """Get path for SQLite database."""
        return self.base_path / "knowledge_base.db"

    def get_graph_path(self) -> Path:
        """Get path for NetworkX graph file."""
        return self.base_path / "graph.pkl"

    def _get_date_subdir(self) -> Path:
        """Get date-based subdirectory path."""
        today = datetime.now().strftime("%Y-%m-%d")
        return Path(today)

    def get_capture_path(self, filename: str) -> Path:
        """Get path for storing a new capture."""
        date_dir = self._get_date_subdir()
        captures_dir = self.base_path / "data" / "captures" / date_dir
        captures_dir.mkdir(exist_ok=True)

        return captures_dir / filename

    def get_processed_path(self, filename: str) -> Path:
        """Get path for storing processed results."""
        date_dir = self._get_date_subdir()
        processed_dir = self.base_path / "data" / "processed" / date_dir
        processed_dir.mkdir(exist_ok=True)

        return processed_dir / filename

    def get_temp_path(self, filename: str) -> Path:
        """Get temporary file path."""
        temp_dir = self.base_path / "data" / "temp"
        return temp_dir / filename

    def store_capture(self, source_path: Path, filename: str) -> Path:
        """Store a capture file in the captures directory."""
        dest_path = self.get_capture_path(filename)
        shutil.copy2(source_path, dest_path)
        logger.info(f"Stored capture: {dest_path}")
        return dest_path

    def store_processed(self, source_path: Path, filename: str) -> Path:
        """Store a processed file in the processed directory."""
        dest_path = self.get_processed_path(filename)
        shutil.copy2(source_path, dest_path)
        logger.info(f"Stored processed file: {dest_path}")
        return dest_path

    def cleanup_temp(self) -> None:
        """Clean up temporary files."""
        temp_dir = self.base_path / "data" / "temp"
        shutil.rmtree(temp_dir)
        temp_dir.mkdir(exist_ok=True)
        logger.info("Cleaned up temporary files") 