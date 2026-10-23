"""Coverage for proposal-time validation of appearance (ui) consent receipts."""

import pytest
from pydantic import ValidationError

from api.services.setup_assistant.agent_graph.setup_agent_tooling.schemas import (
    SetupProposeConsentReceiptInput,
    SetupProposeMutationInput,
)


def build_receipt_input(ui_updates: dict) -> dict:
    return {
        "title": "Update appearance",
        "rationale": "Apply the requested colors.",
        "mutation_tool_name": "update_basil_settings",
        "mutation_payload": {"settings": {"ui": ui_updates}},
    }


def test_appearance_consent_receipt_accepts_a_valid_partial_update() -> None:
    receipt = SetupProposeConsentReceiptInput(**build_receipt_input({"background_color_red": 0.2}))

    assert receipt.mutation_payload["settings"]["ui"]["background_color_red"] == 0.2


def test_appearance_consent_receipt_rejects_out_of_range_rgb() -> None:
    with pytest.raises(ValidationError, match="must be a number from 0.0 through 1.0"):
        SetupProposeConsentReceiptInput(**build_receipt_input({"text_color_red": -0.1}))


def test_appearance_consent_receipt_rejects_unknown_ui_key() -> None:
    with pytest.raises(ValidationError, match="is not allowed during setup"):
        SetupProposeConsentReceiptInput(**build_receipt_input({"border_color_red": 0.5}))


def test_appearance_consent_receipt_rejects_font_outside_catalog() -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        SetupProposeConsentReceiptInput(**build_receipt_input({"preferred_font": "Comic Sans"}))


def test_generic_appearance_proposal_rejects_out_of_range_rgb() -> None:
    with pytest.raises(ValidationError, match="must be a number from 0.0 through 1.0"):
        SetupProposeMutationInput(
            title="Update appearance",
            rationale="Apply the requested colors.",
            tool_name="update_basil_settings",
            payload={"settings": {"ui": {"background_color_blue": 1.1}}},
        )


def test_non_appearance_consent_receipt_is_unaffected() -> None:
    receipt = SetupProposeConsentReceiptInput(
        title="Enable hotkey monitoring",
        rationale="Turn on startup monitoring.",
        mutation_tool_name="update_basil_settings",
        mutation_payload={"settings": {"behavior": {"enable_monitoring_at_startup": True}}},
    )

    assert receipt.mutation_payload["settings"]["behavior"]["enable_monitoring_at_startup"] is True


def test_non_update_settings_tool_is_unaffected_by_appearance_validator() -> None:
    receipt = SetupProposeConsentReceiptInput(
        title="Refresh a connection",
        rationale="Refresh available tools.",
        mutation_tool_name="refresh_connection_tools",
        mutation_payload={"connection_id": "github"},
    )

    assert receipt.mutation_payload["connection_id"] == "github"
