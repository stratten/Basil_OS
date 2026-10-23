"""Mechanical meeting detection: a backend loop that probes the client for
meeting-app audio activity (via CoreAudio HAL reads, no audio tap) and surfaces
a start-transcription prompt.

Deliberately independent of ambient_suggestions: ambient is model-driven (LLM
per tick, relaxed cadence); this is purely mechanical and runs on its own tight
loop with its own settings, store-less broadcast, and surface.
"""
