from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings

from api.core.runtime.validation_profile import (
    ValidationRuntimeProfile,
    is_validation_runtime,
)


def _default_models_dir() -> str:
    if is_validation_runtime():
        profile = ValidationRuntimeProfile.from_environment()
        if profile.shared_models_root is not None:
            return str(profile.shared_models_root)
        return str(profile.runtime_root / "models")
    return str(Path.home() / ".basil" / "models")


def _default_data_dir() -> str:
    if is_validation_runtime():
        profile = ValidationRuntimeProfile.from_environment()
        profile.ensure_directories()
        return str(profile.data_root)
    return str(Path.home() / ".basil" / "data")

class Settings(BaseSettings):
    """API settings loaded from environment variables."""
    models_dir: str = Field(default_factory=_default_models_dir)
    data_dir: str = Field(default_factory=_default_data_dir)
    debug: bool = True

    class Config:
        env_prefix = "BASIL_"
        case_sensitive = False
        frozen = True  # Make the class immutable

    def __hash__(self):
        return hash((self.models_dir, self.data_dir, self.debug))


@lru_cache()
def get_settings() -> Settings:
    """Get settings singleton."""
    return Settings() 


def get_models_dir(settings: Settings | None = None) -> Path:
    """Return Basil's canonical runtime/download model directory."""
    selected_settings = settings or get_settings()
    models_dir = Path(selected_settings.models_dir).expanduser()
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir