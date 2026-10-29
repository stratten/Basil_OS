"""Contract tests for adapter-neutral material-operation envelopes."""

import pytest

from api.services.agent_processing.shared.material_operation_receipts import (
    LedgerEntityReference,
    MaterialOperationContractError,
    MaterialOperationEnvelope,
    MaterialOperationReceipt,
    extract_material_operation_envelope,
)


def _receipt(**overrides):
    values = {
        "entity": LedgerEntityReference(
            "file",
            "filesystem",
            {"host_scope": "local"},
            "/tmp/example",
        ),
        "requested_effect": {"operation": "create"},
        "execution_state": "succeeded",
        "observed_postcondition": {"exists": True},
        "verification_status": "verified",
        "evidence": {"fingerprint": "abc"},
    }
    values.update(overrides)
    return MaterialOperationReceipt(**values)


def test_canonical_entity_scope_has_deterministic_identity():
    first = LedgerEntityReference("file", "filesystem", {"b": 2, "a": 1}, "/tmp/a")
    second = LedgerEntityReference("file", "filesystem", {"a": 1, "b": 2}, "/tmp/a")

    assert first.identity_key == second.identity_key
    assert first.source_scope_json == '{"a": 1, "b": 2}'


@pytest.mark.parametrize(
    "receipt",
    [
        lambda: _receipt(execution_state="unknown"),
        lambda: _receipt(verification_status="unknown"),
        lambda: _receipt(evidence={}),
        lambda: _receipt(observed_postcondition={}),
    ],
)
def test_receipt_rejects_invalid_states_or_unsupported_verified_claims(receipt):
    with pytest.raises(MaterialOperationContractError):
        receipt()


def test_envelope_rejects_duplicate_entity_references():
    receipt = _receipt()
    with pytest.raises(MaterialOperationContractError, match="duplicate"):
        MaterialOperationEnvelope(receipts=(receipt, receipt))


def test_legacy_output_is_not_promoted_to_a_material_receipt():
    assert extract_material_operation_envelope(
        {"outcome_review": {"material_write": True, "verification_status": "verified"}}
    ) is None
