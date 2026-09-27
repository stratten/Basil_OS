"""Shared dependencies for transcription routes."""

from api.core.knowledge.sqlite.transcription_repository import TranscriptionRepository


transcription_repository = TranscriptionRepository()
