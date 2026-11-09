"""Guards for the email tool description reduction: the shared principles are published once on the tools they govern, and explicit schemas no longer repeat the Python signature."""

from __future__ import annotations

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.progress_metadata import SERVICE_SCOPE_NOTES, generate_tool_description
from api.services.agent_processing.tools.direct_application_interactions.email_integration import email_service_capabilities
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import EmailClientService

# The 14 email tool descriptions were 32,639 characters before the reduction and about 9,700 after it.
EMAIL_DESCRIPTION_CHAR_CEILING = 11_000

DRAFT_METHODS = {"create_new_email_draft", "create_reply_email_draft"}

# Methods with an explicit input model, whose JSON schema already carries every parameter, type, and default.
EXPLICIT_SCHEMA_METHODS = {
    "get_emails",
    "get_email_metadata",
    "expand_email_details",
    "search_emails",
    "create_new_email_draft",
    "create_reply_email_draft",
    "organize_emails",
    "bulk_organize_emails",
}

# Methods that rely on a dynamic schema, so the signature is still the only place their real types appear.
DYNAMIC_SCHEMA_METHODS = {"get_folders", "create_folder", "get_inbox_emails", "process_email_request", "create_email_draft", "reply_to_email"}


class _EmailServiceStub:
    """Exposes the real EmailClientService methods so capability building sees the real docstrings and signatures."""


for _method_name in email_service_capabilities._SLIM_DOCS_BY_METHOD:
    if hasattr(EmailClientService, _method_name):
        setattr(_EmailServiceStub, _method_name, getattr(EmailClientService, _method_name))


@pytest.fixture(scope="module")
def capabilities():
    return email_service_capabilities.build_service_capabilities(_EmailServiceStub())


@pytest.fixture(scope="module")
def descriptions(capabilities):
    return {
        method_name: generate_tool_description("email_service", method_name, method_info, capabilities["execution_principles"])
        for method_name, method_info in capabilities["methods"].items()
    }


def test_every_email_method_is_covered_by_the_scope_lists(descriptions):
    assert set(descriptions) == EXPLICIT_SCHEMA_METHODS | DYNAMIC_SCHEMA_METHODS


def test_total_email_description_size_stays_under_the_ceiling(descriptions):
    assert sum(len(text) for text in descriptions.values()) < EMAIL_DESCRIPTION_CHAR_CEILING


def test_only_the_draft_tools_carry_the_execution_principles(descriptions):
    carrying = {method_name for method_name, text in descriptions.items() if "Execution Principles:" in text}
    assert carrying == DRAFT_METHODS


def test_every_published_principle_still_reaches_the_model_on_each_draft_tool(capabilities, descriptions):
    published = capabilities["execution_principles"][:6]
    assert len(published) == 6
    for method_name in DRAFT_METHODS:
        for principle in published:
            assert principle in descriptions[method_name], f"{method_name} lost: {principle[:50]}"


def test_the_outlook_verification_and_applescript_carve_out_rules_survive_somewhere(descriptions):
    combined = "\n".join(descriptions.values())
    assert "OUTLOOK DRAFT VERIFICATION" in combined
    assert "read-only inspection the email tools do not expose" in combined
    assert "Direct sending is disabled" in combined


@pytest.mark.parametrize("method_name", sorted(EXPLICIT_SCHEMA_METHODS))
def test_methods_with_an_explicit_schema_do_not_repeat_the_signature(descriptions, method_name):
    assert "Signature:" not in descriptions[method_name]


@pytest.mark.parametrize("method_name", sorted(DYNAMIC_SCHEMA_METHODS))
def test_methods_with_a_dynamic_schema_keep_the_signature(descriptions, method_name):
    assert "Signature:" in descriptions[method_name]


def test_every_description_still_starts_with_the_method_docstring(capabilities, descriptions):
    for method_name, method_info in capabilities["methods"].items():
        assert descriptions[method_name].removeprefix(SERVICE_SCOPE_NOTES["email_service"]).startswith(method_info["doc"].strip()[:80])


def test_every_email_tool_says_it_serves_only_the_mail_app_and_outlook(descriptions):
    for method_name, text in descriptions.items():
        assert text.startswith("Mail app or Outlook only, not Gmail or other connections."), method_name


def test_every_email_tool_still_says_it_serves_only_the_mail_app_and_outlook_under_a_slim_profile(capabilities):
    from api.core.models.reasoning.model_runtime_profile import resolve_runtime_model_profile
    from types import SimpleNamespace

    profile = resolve_runtime_model_profile(SimpleNamespace(model_name="Qwen-qwen3-8b-mlx-4bit"))
    for method_name, method_info in capabilities["methods"].items():
        text = generate_tool_description("email_service", method_name, method_info, capabilities["execution_principles"], profile=profile)
        assert text.startswith("Mail app or Outlook only, not Gmail or other connections."), method_name


def test_a_service_without_a_scope_note_gets_no_prefix():
    method_info = {"doc": "Does a thing.", "signature": "(self)"}
    assert generate_tool_description("some_other_service", "do_thing", method_info, []).startswith("Does a thing.")


def test_a_service_that_does_not_set_the_flag_still_carries_principles_and_signature():
    method_info = {"doc": "Does a thing.", "signature": "(self, value: str)"}
    text = generate_tool_description("some_other_service", "do_thing", method_info, ["RULE: always do the thing."])
    assert "Signature: (self, value: str)" in text
    assert "Execution Principles:" in text
    assert "RULE: always do the thing." in text


def test_a_method_flagged_false_omits_the_principles_but_keeps_its_signature_when_the_schema_is_dynamic():
    method_info = {"doc": "Does a thing.", "signature": "(self, value: str)", "carries_execution_principles": False}
    text = generate_tool_description("some_other_service", "do_thing", method_info, ["RULE: always do the thing."])
    assert "Signature: (self, value: str)" in text
    assert "Execution Principles:" not in text
