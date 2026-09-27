# Wake Word Service

This package owns the backend wake-word and microphone lifecycle only.

- `wake_word_service.py` wires wake-word detection, backend audio capture, transcription service access, and listener health checks.
- `wake_word_detector.py`, `audio_capturer.py`, and `ffmpeg_utils.py` are the low-level audio components.
- `wake_word_manager.py` handles wake-word callbacks and hands accepted captures to the agent-task submission path.

Agent-task processing, routing, approval, and workflow execution live under `api/services/agent_processing`.
