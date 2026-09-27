"""Extract contact identity candidates from Activity Capture content.

This produces *candidates* only. It never writes ``contact_relationships`` and
never asserts a relationship. The two stages are:

1. Deterministic parsing of explicit email headers and bare email addresses in
   the OCR ``extracted_text``. This is cheap, offline, and high precision.
2. Optional agentic interpretation using an already-loaded reasoning model to
   associate visible names/organizations/titles with email addresses. The model
   is told to distinguish observed identity facts from inferred relationships
   and to supply a confidence and reason for every candidate.

The agentic stage is best-effort: if the model is missing or its output cannot
be parsed/validated, the extractor falls back to the deterministic candidates.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..personalization_models import (
    ContactIdentityObservationCreate,
    ObservationSourceType,
)
from .contact_context import (
    EMAIL_ADDRESS_PATTERN,
    EmailInteractionKind,
    EmailParticipant,
    extract_email_participant_context,
    normalize_email_address,
)

logger = logging.getLogger(__name__)

# Confidence assigned to deterministic candidates by provenance. Header
# participants carrying a display name are the strongest signal; bare addresses
# found loose in body text are weak and must not drive generation on their own.
_CONFIDENCE_HEADER_NAMED = 0.85
_CONFIDENCE_HEADER_BARE = 0.6
_CONFIDENCE_BODY_ADDRESS = 0.35

_HEADER_LABELS = {
    "From": "From",
    "To": "To",
    "Cc": "Cc",
    "Bcc": "Bcc",
}


class ContactCandidateExtractor:
    """Two-stage contact identity candidate extractor."""

    def __init__(
        self,
        min_agentic_confidence: float = 0.5,
        max_text_chars: int = 6000,
    ) -> None:
        """Initialize the extractor.

        Args:
            min_agentic_confidence: Minimum confidence an agentic candidate must
                report to be retained.
            max_text_chars: Upper bound on text length sent to the model.
        """
        self.min_agentic_confidence = min_agentic_confidence
        self.max_text_chars = max_text_chars

    # ------------------------------------------------------------------
    # Stage 1: deterministic
    # ------------------------------------------------------------------

    def extract_deterministic_candidates(
        self,
        *,
        extracted_text: Optional[str],
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        source_activity_id: Optional[str] = None,
    ) -> List[ContactIdentityObservationCreate]:
        """Parse explicit email headers and bare addresses into candidates."""
        if not extracted_text or not extracted_text.strip():
            return []

        candidates: Dict[str, ContactIdentityObservationCreate] = {}

        context = extract_email_participant_context(
            extracted_text, EmailInteractionKind.GENERIC
        )
        header_groups = (
            ("From", context.from_participants),
            ("To", context.to_participants),
            ("Cc", context.cc_participants),
            ("Bcc", context.bcc_participants),
        )
        seen_header_emails = set()
        for header_label, participants in header_groups:
            for participant in participants:
                seen_header_emails.add(participant.email)
                self._merge_candidate(
                    candidates,
                    self._candidate_from_header_participant(
                        participant=participant,
                        header_label=header_label,
                        app_name=app_name,
                        window_title=window_title,
                        source_activity_id=source_activity_id,
                    ),
                )

        for match in EMAIL_ADDRESS_PATTERN.finditer(extracted_text):
            normalized = normalize_email_address(match.group(0))
            if not normalized or normalized in seen_header_emails:
                continue
            self._merge_candidate(
                candidates,
                ContactIdentityObservationCreate(
                    source_type=ObservationSourceType.ACTIVITY_CAPTURE,
                    source_activity_id=source_activity_id,
                    source_app_name=app_name,
                    source_window_title=window_title,
                    normalized_email=normalized,
                    confidence=_CONFIDENCE_BODY_ADDRESS,
                    reason="Email address found in screen text",
                    raw_evidence=self._snippet(extracted_text, match.start(), match.end()),
                ),
            )

        return list(candidates.values())

    def _candidate_from_header_participant(
        self,
        *,
        participant: EmailParticipant,
        header_label: str,
        app_name: Optional[str],
        window_title: Optional[str],
        source_activity_id: Optional[str],
    ) -> ContactIdentityObservationCreate:
        has_name = bool(participant.display_name)
        confidence = _CONFIDENCE_HEADER_NAMED if has_name else _CONFIDENCE_HEADER_BARE
        relationship_hint = "sender" if header_label == "From" else "recipient"
        return ContactIdentityObservationCreate(
            source_type=ObservationSourceType.ACTIVITY_CAPTURE,
            source_activity_id=source_activity_id,
            source_app_name=app_name,
            source_window_title=window_title,
            normalized_email=participant.email,
            display_name=participant.display_name,
            relationship_hint=relationship_hint,
            confidence=confidence,
            reason=f"Parsed from {header_label} header",
            raw_evidence=participant.label,
        )

    # ------------------------------------------------------------------
    # Stage 2: agentic
    # ------------------------------------------------------------------

    async def extract_agentic_candidates(
        self,
        *,
        model: Any,
        extracted_text: Optional[str],
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        source_activity_id: Optional[str] = None,
    ) -> List[ContactIdentityObservationCreate]:
        """Use a reasoning model to associate identity facts with addresses."""
        if model is None or not extracted_text or not extracted_text.strip():
            return []

        prompt = self._build_agentic_prompt(
            extracted_text=extracted_text,
            app_name=app_name,
            window_title=window_title,
            entities=entities,
        )
        try:
            raw_result = await model.generate_response(prompt=prompt)
        except Exception as exc:  # noqa: BLE001 - best-effort, never fatal
            logger.warning(
                "Agentic contact candidate generation failed (%s)",
                type(exc).__name__,
            )
            return []

        parsed = self._parse_candidate_payload(raw_result)
        if not parsed:
            return []

        candidates: Dict[str, ContactIdentityObservationCreate] = {}
        for raw_candidate in parsed:
            candidate = self._validate_agentic_candidate(
                raw_candidate=raw_candidate,
                app_name=app_name,
                window_title=window_title,
                source_activity_id=source_activity_id,
            )
            if candidate is not None:
                self._merge_candidate(candidates, candidate)
        return list(candidates.values())

    def _build_agentic_prompt(
        self,
        *,
        extracted_text: str,
        app_name: Optional[str],
        window_title: Optional[str],
        entities: Optional[List[Dict[str, Any]]],
    ) -> str:
        truncated_text = extracted_text[: self.max_text_chars]
        entities_block = ""
        if entities:
            try:
                entities_block = json.dumps(entities)[: self.max_text_chars]
            except (TypeError, ValueError):
                entities_block = ""

        return (
            "You extract CONTACT IDENTITY FACTS that are directly visible in "
            "on-screen content. You must only report identity facts you can see, "
            "such as a person's email address paired with their name, organization, "
            "or job title. Never infer a relationship, never guess an email address, "
            "and never invent fields.\n\n"
            f"Application: {app_name or 'unknown'}\n"
            f"Window title: {window_title or 'unknown'}\n\n"
            "Detected entities (may be empty):\n"
            f"{entities_block}\n\n"
            "Screen content:\n"
            f"{truncated_text}\n\n"
            "Return ONLY raw JSON (no markdown, no commentary) shaped exactly as:\n"
            "{\n"
            '  "candidates": [\n'
            "    {\n"
            '      "email": "person@example.com",\n'
            '      "display_name": "Visible name or null",\n'
            '      "organization_name": "Visible organization or null",\n'
            '      "job_title": "Visible job title or null",\n'
            '      "relationship_hint": "short role hint only, never a relationship type",\n'
            '      "confidence": 0.0,\n'
            '      "reason": "What on screen supports this",\n'
            '      "evidence": "Short verbatim snippet"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "1. Only include a candidate when an email address is actually visible.\n"
            "2. Use null for any field you cannot see; do not fabricate.\n"
            "3. confidence is your certainty the identity fact is correct (0.0-1.0).\n"
            "4. Do not output a relationship type such as colleague, manager, or client.\n"
            "5. If no email addresses are visible, return {\"candidates\": []}."
        )

    def _validate_agentic_candidate(
        self,
        *,
        raw_candidate: Dict[str, Any],
        app_name: Optional[str],
        window_title: Optional[str],
        source_activity_id: Optional[str],
    ) -> Optional[ContactIdentityObservationCreate]:
        if not isinstance(raw_candidate, dict):
            return None

        normalized_email = normalize_email_address(
            self._clean_field(raw_candidate.get("email"))
        )
        if not normalized_email:
            return None

        confidence = self._coerce_confidence(raw_candidate.get("confidence"))
        if confidence < self.min_agentic_confidence:
            return None

        return ContactIdentityObservationCreate(
            source_type=ObservationSourceType.ACTIVITY_CAPTURE,
            source_activity_id=source_activity_id,
            source_app_name=app_name,
            source_window_title=window_title,
            normalized_email=normalized_email,
            display_name=self._clean_field(raw_candidate.get("display_name")),
            organization_name=self._clean_field(raw_candidate.get("organization_name")),
            job_title=self._clean_field(raw_candidate.get("job_title")),
            relationship_hint=self._clean_field(raw_candidate.get("relationship_hint")),
            confidence=confidence,
            reason=self._clean_field(raw_candidate.get("reason")),
            raw_evidence=self._clean_field(raw_candidate.get("evidence")),
        )

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------

    async def extract_candidates(
        self,
        *,
        extracted_text: Optional[str],
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        source_activity_id: Optional[str] = None,
        model: Any = None,
    ) -> List[ContactIdentityObservationCreate]:
        """Run deterministic extraction, then merge optional agentic candidates."""
        merged: Dict[str, ContactIdentityObservationCreate] = {}

        for candidate in self.extract_deterministic_candidates(
            extracted_text=extracted_text,
            app_name=app_name,
            window_title=window_title,
            source_activity_id=source_activity_id,
        ):
            self._merge_candidate(merged, candidate)

        if model is not None:
            for candidate in await self.extract_agentic_candidates(
                model=model,
                extracted_text=extracted_text,
                app_name=app_name,
                window_title=window_title,
                entities=entities,
                source_activity_id=source_activity_id,
            ):
                self._merge_candidate(merged, candidate)

        return list(merged.values())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _merge_candidate(
        self,
        candidates: Dict[str, ContactIdentityObservationCreate],
        candidate: ContactIdentityObservationCreate,
    ) -> None:
        """Merge a candidate into the accumulator, keyed by normalized email.

        Keeps the higher confidence, fills missing identity fields from whichever
        candidate supplies them, and preserves the strongest available reason.
        """
        existing = candidates.get(candidate.normalized_email)
        if existing is None:
            candidates[candidate.normalized_email] = candidate
            return

        winner = existing if existing.confidence >= candidate.confidence else candidate
        other = candidate if winner is existing else existing
        merged = ContactIdentityObservationCreate(
            source_type=winner.source_type,
            source_activity_id=winner.source_activity_id or other.source_activity_id,
            source_app_name=winner.source_app_name or other.source_app_name,
            source_window_title=winner.source_window_title or other.source_window_title,
            normalized_email=winner.normalized_email,
            display_name=winner.display_name or other.display_name,
            organization_name=winner.organization_name or other.organization_name,
            job_title=winner.job_title or other.job_title,
            relationship_hint=winner.relationship_hint or other.relationship_hint,
            confidence=max(existing.confidence, candidate.confidence),
            reason=winner.reason or other.reason,
            raw_evidence=winner.raw_evidence or other.raw_evidence,
        )
        candidates[candidate.normalized_email] = merged

    def _parse_candidate_payload(self, raw_result: Any) -> List[Dict[str, Any]]:
        """Parse a model response into a list of raw candidate dicts."""
        if not isinstance(raw_result, str) or not raw_result.strip():
            return []

        parsed = self._loads_or_extract(raw_result)
        if parsed is None:
            logger.debug("Could not parse contact candidate JSON from model output")
            return []

        if isinstance(parsed, dict):
            candidates = parsed.get("candidates")
            if isinstance(candidates, list):
                return [c for c in candidates if isinstance(c, dict)]
            return []
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, dict)]
        return []

    def _loads_or_extract(self, raw_result: str) -> Optional[Any]:
        try:
            return json.loads(raw_result)
        except json.JSONDecodeError:
            pass

        # Strip common markdown fences, then try the largest JSON object/array.
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, raw_result, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _coerce_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        if confidence < 0.0:
            return 0.0
        if confidence > 1.0:
            return 1.0
        return confidence

    @staticmethod
    def _clean_field(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none", "n/a", "unknown"}:
            return None
        return text

    @staticmethod
    def _snippet(text: str, start: int, end: int, radius: int = 40) -> str:
        snippet_start = max(0, start - radius)
        snippet_end = min(len(text), end + radius)
        return text[snippet_start:snippet_end].strip()
