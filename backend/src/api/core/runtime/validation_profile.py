"""Developer-local validation runtime isolation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ValidationRuntimeConfigurationError(RuntimeError):
    """Raised when a validation backend launch is not safely isolated."""


def is_validation_runtime(environment: Mapping[str, str] | None = None) -> bool:
    selected_environment = environment or os.environ
    return selected_environment.get("BASIL_RUNTIME_PROFILE") == "validation"


@dataclass(frozen=True)
class ValidationRuntimeProfile:
    session_root: Path
    session_home: Path
    port: int
    manifest_token: str
    shared_models_root: Path | None
    force_approval_prompts: bool = False

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ValidationRuntimeProfile":
        selected_environment = environment or os.environ
        if not is_validation_runtime(selected_environment):
            raise ValidationRuntimeConfigurationError(
                "BASIL_RUNTIME_PROFILE must be validation."
            )

        raw_session_root = selected_environment.get("BASIL_VALIDATION_SESSION_ROOT", "")
        if not raw_session_root:
            raise ValidationRuntimeConfigurationError(
                "BASIL_VALIDATION_SESSION_ROOT is required."
            )
        session_root = Path(raw_session_root)
        if not session_root.is_absolute():
            raise ValidationRuntimeConfigurationError(
                "BASIL_VALIDATION_SESSION_ROOT must be absolute."
            )
        session_root = session_root.resolve()
        session_home = session_root / "home"
        if not session_home.is_relative_to(session_root):
            raise ValidationRuntimeConfigurationError(
                "Validation session home must remain inside the session root."
            )
        if Path.home().resolve() != session_home.resolve():
            raise ValidationRuntimeConfigurationError(
                "Validation backend HOME must be the session-local synthetic home."
            )

        host = selected_environment.get("BASIL_HOST", "")
        if host not in {"localhost", "127.0.0.1"}:
            raise ValidationRuntimeConfigurationError(
                "Validation backends must bind to a loopback host."
            )
        try:
            port = int(selected_environment["BASIL_PORT"])
        except (KeyError, ValueError) as error:
            raise ValidationRuntimeConfigurationError(
                "BASIL_PORT must be an explicit integer."
            ) from error
        if not 1 <= port <= 65535:
            raise ValidationRuntimeConfigurationError(
                "BASIL_PORT must be between 1 and 65535."
            )

        manifest_token = selected_environment.get(
            "BASIL_VALIDATION_SESSION_TOKEN",
            "",
        ).strip()
        if not manifest_token:
            raise ValidationRuntimeConfigurationError(
                "BASIL_VALIDATION_SESSION_TOKEN is required."
            )

        raw_models_root = selected_environment.get("BASIL_VALIDATION_SHARED_MODELS_ROOT")
        shared_models_root = (
            Path(raw_models_root).expanduser().resolve()
            if raw_models_root
            else None
        )
        force_approval_prompts = (
            selected_environment.get("BASIL_VALIDATION_FORCE_APPROVAL_PROMPTS") == "1"
        )
        return cls(
            session_root=session_root,
            session_home=session_home,
            port=port,
            manifest_token=manifest_token,
            shared_models_root=shared_models_root,
            force_approval_prompts=force_approval_prompts,
        )

    @property
    def runtime_root(self) -> Path:
        return self.session_home / ".basil"

    @property
    def config_root(self) -> Path:
        return self.runtime_root / "config"

    @property
    def data_root(self) -> Path:
        return self.runtime_root / "data"

    @property
    def fixtures_root(self) -> Path:
        return self.session_root / "fixtures"

    def ensure_directories(self) -> None:
        for directory in (
            self.session_home,
            self.runtime_root,
            self.config_root,
            self.data_root,
            self.fixtures_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def owns(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.session_root)
