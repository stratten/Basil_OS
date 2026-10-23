from unittest.mock import MagicMock

from api.services.capture.manual.capture_handler import CaptureHandler


def test_capture_handler_uses_canonical_sqlite_service(monkeypatch) -> None:
    sqlite_service = MagicMock()
    monkeypatch.setattr(
        "api.services.capture.manual.capture_handler.get_sqlite_knowledge_service",
        lambda: sqlite_service,
    )

    handler = CaptureHandler(
        model_service=MagicMock(),
        storage=MagicMock(),
        settings=MagicMock(),
    )

    assert handler.knowledge_base is sqlite_service
