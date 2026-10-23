from pathlib import Path
from typing import Dict, Any, List
import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

class ModelConfig(BaseModel):
    type: str
    path: Path
    max_memory: str

class StorageConfig(BaseModel):
    db_path: Path
    captures_path: Path
    temp_path: Path

class APIProvider(BaseModel):
    name: str
    models: List[str]
    requires_key: bool = True

class APIKeysConfig(BaseModel):
    providers: List[APIProvider]

class AppConfig(BaseSettings):
    name: str = "Basil"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    model: ModelConfig
    storage: StorageConfig
    api_keys: APIKeysConfig = None

    @classmethod
    def load_from_yaml(cls, config_path: Path) -> "AppConfig":
        """Load configuration from YAML file"""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
            
        with open(config_path) as f:
            config_dict = yaml.safe_load(f)
            
        # Extract app section and merge with other sections
        app_config = config_dict.pop("app", {})
        config_dict.update(app_config)
            
        return cls(**config_dict)

    def ensure_paths(self) -> None:
        """Ensure all required paths exist"""
        paths = [
            self.model.path,
            self.storage.db_path,
            self.storage.captures_path,
            self.storage.temp_path
        ]
        
        for path in paths:
            path = Path(str(path).replace("~", str(Path.home())))
            path.mkdir(parents=True, exist_ok=True) 