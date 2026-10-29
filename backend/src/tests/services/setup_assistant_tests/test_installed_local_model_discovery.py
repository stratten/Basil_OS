"""Any installed local model counts as installed; only the recommended starter models used to."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from api.core.utc_time import utc_now_naive
from api.routes.setup_assistant.models import (
    SetupDiscoveryFact,
    SetupDiscoveryFactKind,
    SetupDiscoverySource,
)
from api.services.setup_assistant.agent_graph.agenda_catalog import applicable_catalog_seed
from api.services.setup_assistant.agent_graph.setup_agent_system_prompt import build_setup_agent_system_prompt
from api.services.setup_assistant.discovery_service import SetupAssistantDiscoveryService

NOT_THE_STARTER_REASONING = {"Qwen": {"variants": {"qwen3-8b-instruct-q4km": {}, "qwen35-4b-q4km": {}}}}
NOT_THE_STARTER_TRANSCRIPTION = {"OpenAI": {"variants": {"whisper-small.en": {}}}}


class _Downloader:
    def __init__(self, installed):
        self._installed = installed

    def get_installed_models(self):
        if isinstance(self._installed, Exception):
            raise self._installed
        return self._installed


def _service(installed) -> SetupAssistantDiscoveryService:
    model_service = SimpleNamespace(model_downloader=_Downloader(installed), is_model_downloaded=lambda *_: False)
    return SetupAssistantDiscoveryService(model_service)


def _facts(installed):
    return _service(installed)._build_installed_local_model_facts(utc_now_naive())


def _by_id(facts):
    return {fact.id: fact for fact in facts}


def _seed_ids(facts):
    return {item["id"] for item in applicable_catalog_seed(facts)}


def _starter_fact(model_id: str, description: str, value: str) -> SetupDiscoveryFact:
    return SetupDiscoveryFact(
        id=f"starter-model-{model_id}",
        source=SetupDiscoverySource.model_status,
        kind=SetupDiscoveryFactKind.available_model,
        value=value,
        confidence=1.0,
        collected_at=utc_now_naive(),
        user_visible_summary="starter",
        metadata={"model_id": model_id, "description": description, "model_type": model_id.split("-")[0]},
    )


def test_other_installed_reasoning_models_count_as_installed():
    facts = _by_id(_facts({**NOT_THE_STARTER_REASONING, **NOT_THE_STARTER_TRANSCRIPTION}))

    reasoning = facts["local-reasoning-models-installed"]
    assert reasoning.value == "true"
    assert reasoning.metadata["installed_count"] == "2"
    assert "Qwen-qwen3-8b-instruct-q4km" in reasoning.metadata["installed_model_ids"]
    assert facts["local-transcription-models-installed"].value == "true"


def test_nothing_installed_reports_false_and_an_empty_list():
    facts = _by_id(_facts({}))

    assert facts["local-reasoning-models-installed"].value == "false"
    assert facts["local-reasoning-models-installed"].metadata["installed_model_ids"] == ""
    assert facts["local-transcription-models-installed"].value == "false"


def test_a_transcription_model_does_not_count_as_a_reasoning_model_and_the_reverse():
    only_transcription = _by_id(_facts(NOT_THE_STARTER_TRANSCRIPTION))
    only_reasoning = _by_id(_facts(NOT_THE_STARTER_REASONING))

    assert only_transcription["local-reasoning-models-installed"].value == "false"
    assert only_transcription["local-transcription-models-installed"].value == "true"
    assert only_reasoning["local-reasoning-models-installed"].value == "true"
    assert only_reasoning["local-transcription-models-installed"].value == "false"


def test_an_unreadable_install_state_reports_nothing_rather_than_a_false_claim():
    assert _facts(RuntimeError("models directory unreadable")) == []


def test_the_agenda_skips_model_downloads_when_other_models_are_installed_even_if_the_starters_are_missing():
    facts = [
        *_facts({**NOT_THE_STARTER_REASONING, **NOT_THE_STARTER_TRANSCRIPTION}),
        _starter_fact("Qwen-qwen35-9b-q4km", "Reasoning model for suggestions (5.7GB)", "missing"),
        _starter_fact("OpenAI-whisper-tiny.en", "Fast English transcription (151MB)", "missing"),
    ]

    seeded = _seed_ids(facts)

    assert "setup_local_reasoning_model" not in seeded
    assert "setup_local_transcription_model" not in seeded


def test_the_agenda_offers_each_download_only_when_that_kind_of_model_is_absent():
    reasoning_only = _seed_ids(_facts(NOT_THE_STARTER_REASONING))
    nothing = _seed_ids(_facts({}))

    assert "setup_local_reasoning_model" not in reasoning_only
    assert "setup_local_transcription_model" in reasoning_only
    assert {"setup_local_reasoning_model", "setup_local_transcription_model"} <= nothing


def test_without_install_facts_the_agenda_falls_back_to_the_starter_facts():
    starters_missing = [
        _starter_fact("Qwen-qwen35-9b-q4km", "Reasoning model for suggestions (5.7GB)", "missing"),
        _starter_fact("OpenAI-whisper-tiny.en", "Fast English transcription (151MB)", "missing"),
    ]
    starters_present = [
        _starter_fact("Qwen-qwen35-9b-q4km", "Reasoning model for suggestions (5.7GB)", "installed"),
        _starter_fact("OpenAI-whisper-tiny.en", "Fast English transcription (151MB)", "installed"),
    ]

    assert {"setup_local_reasoning_model", "setup_local_transcription_model"} <= _seed_ids(starters_missing)
    assert not {"setup_local_reasoning_model", "setup_local_transcription_model"} & _seed_ids(starters_present)


def test_the_prompt_tells_the_agent_not_to_read_a_missing_starter_as_no_local_model():
    prompt = build_setup_agent_system_prompt()

    assert "local-reasoning-models-installed" in prompt
    assert "a starter marked `missing` never means the user has no local model" in prompt
