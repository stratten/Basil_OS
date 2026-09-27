#!/bin/bash

# Ensure we're in the correct directory
cd "$(dirname "$0")/.."

# Add src directory to Python path
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# Run pytest with coverage for transcription-related tests
pytest tests/services/test_transcription_service.py \
      tests/routes/test_websocket.py \
      tests/routes/test_transcription.py \
      tests/core/hotkey/test_audio_transcription_handler.py \
      -v --cov=api/services/transcription \
      --cov=api/routes/websocket \
      --cov=api/routes/transcription \
      --cov=api/core/hotkey/handlers \
      --cov-report=term-missing 