"""Shared library for the evergreen model x scenario smoke harness.

Co-located under backend/scripts/ next to the runnable entry point
(model_scenario_smoke.py) and reused by the optional integration pytest
wrapper, so both the CLI and pytest exercise the exact same per-scenario
invokers instead of two divergent implementations.
"""
