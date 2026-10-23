from pathlib import Path
from typing import Optional

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings

from api.core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)


def _default_storage_directory() -> Path:
    if is_validation_runtime():
        profile = ValidationRuntimeProfile.from_environment()
        profile.ensure_directories()
        return profile.data_root
    return Path.home() / ".basil" / "data"


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = ConfigDict(env_prefix="BASIL_")
    
    # Application settings
    APP_NAME: str = "Basil"
    DEBUG: bool = Field(default=True, description="Debug mode")
    API_VERSION: str = "v1"
    
    # Onboarding status
    HAS_COMPLETED_ONBOARDING: bool = Field(default=False, description="Flag to indicate if the user has completed the onboarding flow")
    
    # Server settings
    HOST: str = Field(default="127.0.0.1", description="Server host")
    PORT: int = Field(default=8000, description="Server port", env="BASIL_PORT")
    ALLOW_LAN_BIND: bool = Field(default=False, description="Reserved for mobile pairing; non-loopback binds are refused until device credentials ship")
    BONJOUR_BROADCAST: bool = Field(default=False, description="Advertise the API server over Bonjour for paired mobile discovery")
    IOS_PAIR_ENABLED: bool = Field(default=False, description="Enable iOS device pairing routes and token checks")
    
    # Path settings
    BASE_DIR: Path = Path(__file__).parent.parent.parent.parent.parent
    STORAGE_DIR: Path = Field(default_factory=_default_storage_directory, description="Main data storage directory")

    # Legacy/cache model setting. Normal runtime and download model storage is
    # resolved through api.settings.get_models_dir(), not this data directory.
    MODEL_CACHE_DIR: Optional[Path] = Field(
        default=None,
        description="Compatibility cache for data-derived model artifacts; not Basil's canonical model directory"
    )
    # Maximum number of model downloads allowed to run concurrently. Default 1
    # gives strict FIFO behavior (the historical Huey-worker semantic). Keep
    # this at 1 while Hugging Face progress is captured by temporary tqdm
    # monkey-patches inside the concrete downloaders; concurrent downloads can
    # otherwise race on shared progress/cancellation hook state.
    MODEL_DOWNLOAD_MAX_CONCURRENT: int = Field(
        default=1,
        description="Maximum simultaneous model downloads (1 = strict FIFO)."
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure storage directory exists (already handled by Field default and Pydantic if path doesn't exist for default factory)
        # However, explicit mkdir is safer for established paths.
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        # Keep the legacy cache path available for compatibility. Do not use
        # this as the canonical model directory for runtime model loading.
        if not self.MODEL_CACHE_DIR:
            self.MODEL_CACHE_DIR = self.STORAGE_DIR / "models"
            self.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

settings = Settings() 