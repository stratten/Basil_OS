"""Sensitive browser fill approval coordinator."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from api.core.models.preferences import (
    BrowserDomainApproval,
    BrowserSensitiveFillPolicy,
)
from api.core.preferences.preferences_io import load_preferences, save_preferences

from .browser_safety import (
    build_sensitive_field_label,
    can_remember_sensitive_fill_domain,
    normalize_domain_from_url,
)
from .browser_sensitive_value_store import get_browser_sensitive_value_store

logger = logging.getLogger(__name__)


@dataclass
class BrowserSensitiveFillRequest:
    browser: str
    selector: str
    url: str
    field_metadata: Mapping[str, Any]
    value_source: str = "agent_argument"
    agent_task_id: Optional[str] = None
    websocket_manager: Any = None


@dataclass
class BrowserSensitiveFillDecision:
    allowed: bool
    reason: str
    domain: str
    remember_domain: bool = False
    sensitive_value_token: Optional[str] = None
    approval_denied: bool = False
    requires_user_input: bool = False


class BrowserSensitiveApprovalManager:
    """Coordinates browser sensitive-fill policy and user approval prompts."""

    _pending_approvals: Dict[str, asyncio.Future] = {}

    async def evaluate_sensitive_fill_request(
        self,
        request: BrowserSensitiveFillRequest,
    ) -> BrowserSensitiveFillDecision:
        """Evaluate policy and request approval when required."""
        preferences = load_preferences()
        settings = preferences.browser_automation
        domain = normalize_domain_from_url(request.url)

        if settings.sensitive_fill_policy == BrowserSensitiveFillPolicy.NEVER:
            return BrowserSensitiveFillDecision(
                allowed=False,
                reason="Sensitive browser fill is disabled in settings.",
                domain=domain,
                requires_user_input=True,
            )

        if settings.sensitive_fill_policy == BrowserSensitiveFillPolicy.APPROVED_DOMAINS:
            matched = next(
                (
                    approval
                    for approval in settings.approved_sensitive_fill_domains
                    if approval.domain == domain and approval.allow_sensitive_fill
                ),
                None,
            )
            if matched:
                matched.last_used = datetime.now()
                matched.use_count += 1
                save_preferences(preferences)
                return BrowserSensitiveFillDecision(
                    allowed=True,
                    reason=f"Domain {domain} is approved for sensitive browser fill.",
                    domain=domain,
                    remember_domain=True,
                )

        if request.websocket_manager is None:
            return BrowserSensitiveFillDecision(
                allowed=False,
                reason="Sensitive browser fill requires interactive approval, but no approval channel is available.",
                domain=domain,
                requires_user_input=True,
            )

        approval_result = await self._request_browser_sensitive_fill_approval(
            request=request,
            domain=domain,
        )
        approved = bool(approval_result.get("approved"))
        remember_domain = bool(approval_result.get("remember_domain"))

        if not approved:
            return BrowserSensitiveFillDecision(
                allowed=False,
                reason="Sensitive browser fill was denied.",
                domain=domain,
                approval_denied=True,
            )

        if remember_domain and can_remember_sensitive_fill_domain(domain):
            self._remember_domain_approval(domain)

        return BrowserSensitiveFillDecision(
            allowed=True,
            reason="Sensitive browser fill approved for this action.",
            domain=domain,
            remember_domain=remember_domain,
            sensitive_value_token=approval_result.get("sensitive_value_token"),
        )

    async def _request_browser_sensitive_fill_approval(
        self,
        request: BrowserSensitiveFillRequest,
        domain: str,
    ) -> Dict[str, Any]:
        approval_id = str(uuid.uuid4())
        future = asyncio.Future()
        BrowserSensitiveApprovalManager._pending_approvals[approval_id] = future

        field_label = build_sensitive_field_label(request.field_metadata, request.selector)
        try:
            approval_event: Dict[str, Any] = {
                "event_type": "execution_approval_request",
                "approval_id": approval_id,
                "command": f"Fill sensitive browser field on {domain or 'unknown domain'}",
                "reason": "A browser action wants to fill a sensitive form field.",
                "risk_level": "high",
                "generalized_pattern": f"browser_sensitive_fill:{domain}",
                "execution_type": "browser_sensitive_fill",
                "context": {
                    "source": "browser_interact",
                    "description": "Sensitive browser fill requires explicit approval",
                },
                "options": {
                    "risk_level": "high",
                    "reason": "Sensitive browser fill requires explicit approval",
                    "show_remember": can_remember_sensitive_fill_domain(domain),
                },
                "browser_metadata": {
                    "domain": domain,
                    "url": request.url,
                    "browser": request.browser,
                    "field_label": field_label,
                    "field_type": request.field_metadata.get("type"),
                    "selector_redacted": request.selector,
                    "value_source": request.value_source,
                    "will_remember_domain_allowed": can_remember_sensitive_fill_domain(domain),
                },
            }
            if request.agent_task_id:
                approval_event["agent_task_id"] = request.agent_task_id

            await request.websocket_manager.broadcast(approval_event)

            from api.core.preferences.preferences_io import load_preferences as _load_preferences
            approval_timeout = _load_preferences().tool_execution.approval_timeout_seconds
            wait_start = time.time()
            result = await asyncio.wait_for(future, timeout=float(approval_timeout))
            logger.info(
                "Browser sensitive-fill approval resolved after %.2fs for domain=%s",
                time.time() - wait_start,
                domain,
            )
            return result if isinstance(result, dict) else {}
        except asyncio.TimeoutError:
            logger.warning("Browser sensitive-fill approval timed out for domain=%s", domain)
            return {"approved": False, "timeout": True}
        finally:
            BrowserSensitiveApprovalManager._pending_approvals.pop(approval_id, None)

    def _remember_domain_approval(self, domain: str) -> None:
        preferences = load_preferences()
        approvals = preferences.browser_automation.approved_sensitive_fill_domains
        existing = next((approval for approval in approvals if approval.domain == domain), None)
        if existing:
            existing.last_used = datetime.now()
            existing.use_count += 1
            existing.allow_sensitive_fill = True
        else:
            approvals.append(BrowserDomainApproval(domain=domain, use_count=1))
        save_preferences(preferences)

    @classmethod
    async def resolve_browser_sensitive_fill_approval(
        cls,
        approval_id: str,
        approved: bool,
        remember_domain: bool = False,
        sensitive_value: Optional[str] = None,
    ) -> bool:
        """Resolve a pending browser-sensitive approval."""
        future = cls._pending_approvals.get(approval_id)
        if future is None or future.done():
            return False

        sensitive_value_token = None
        if approved and sensitive_value:
            sensitive_value_token = get_browser_sensitive_value_store().store_sensitive_value(sensitive_value)

        future.set_result({
            "approved": approved,
            "remember_domain": remember_domain,
            "sensitive_value_token": sensitive_value_token,
        })
        return True


_BROWSER_SENSITIVE_APPROVAL_MANAGER = BrowserSensitiveApprovalManager()


def get_browser_sensitive_approval_manager() -> BrowserSensitiveApprovalManager:
    """Return the process-local browser sensitive approval manager."""
    return _BROWSER_SENSITIVE_APPROVAL_MANAGER

