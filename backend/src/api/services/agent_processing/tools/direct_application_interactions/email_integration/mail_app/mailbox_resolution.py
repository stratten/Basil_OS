"""Resolve conventional mailbox names to the real mailbox names of one Mail account."""

from __future__ import annotations

import time
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

ACCOUNT_FOLDER_SEPARATOR = " / "
LISTING_CACHE_SECONDS = 120.0

_ALIAS_GROUPS: Tuple[frozenset[str], ...] = (
    frozenset({"sent", "sent mail", "sent messages", "sent items"}),
    frozenset({"trash", "deleted items", "deleted messages", "bin"}),
    frozenset({"drafts", "draft"}),
)


class MailboxResolutionError(ValueError):
    """Raised when an account has no mailbox matching the requested name."""


def _normalized(name: str) -> str:
    return " ".join(str(name or "").casefold().split())


def resolve_account_mailbox_name(account: str, requested: str, folder_names: Sequence[str]) -> str:
    """Return the real mailbox name in ``account`` that ``requested`` refers to.

    An exact (case-insensitive) match wins. Otherwise the conventional equivalents of Sent, Trash, and Drafts are interchangeable. When nothing matches, the error lists the real mailbox names so the caller can retry with one of them.
    """
    wanted = _normalized(requested)
    for name in folder_names:
        if _normalized(name) == wanted:
            return name
    for group in _ALIAS_GROUPS:
        if wanted in group:
            for name in folder_names:
                if _normalized(name) in group:
                    return name
    available = ", ".join(f'"{name}"' for name in folder_names) or "(none)"
    raise MailboxResolutionError(
        f'Account "{account}" has no mailbox named "{requested}". Available mailboxes: {available}.'
    )


def mailbox_name_candidates(requested: str) -> List[str]:
    """Return ``requested`` followed by its conventional Sent, Trash, or Drafts equivalents, for in-script lookup without a folder listing."""
    candidates = [requested]
    wanted = _normalized(requested)
    for group in _ALIAS_GROUPS:
        if wanted in group:
            candidates.extend(sorted(name for name in group if name != wanted))
    return candidates


def split_account_token(folder: str) -> Tuple[Optional[str], str]:
    """Split an ``Account / Mailbox`` token; a plain token returns account None."""
    if ACCOUNT_FOLDER_SEPARATOR in folder:
        account, _, mailbox = folder.partition(ACCOUNT_FOLDER_SEPARATOR)
        account, mailbox = account.strip(), mailbox.strip()
        if account and mailbox:
            return account, mailbox
    return None, folder


class AccountMailboxResolver:
    """Resolve ``Account / Mailbox`` tokens against a folder listing cached for 120 seconds."""

    def __init__(
        self,
        list_folders: Callable[[], Awaitable[List[str]]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._list_folders = list_folders
        self._clock = clock
        self._cached_at: Optional[float] = None
        self._tokens: List[str] = []

    async def _listing(self) -> List[str]:
        now = self._clock()
        if self._cached_at is None or now - self._cached_at > LISTING_CACHE_SECONDS:
            self._tokens = list(await self._list_folders())
            self._cached_at = now
        return self._tokens

    def invalidate(self) -> None:
        self._cached_at = None

    async def resolve(self, folder: str) -> str:
        """Return ``folder`` with its mailbox part replaced by the account's real name.

        Plain tokens (``inbox`` and unqualified names) and accounts missing from the listing are returned unchanged.
        """
        account, mailbox = split_account_token(folder)
        if account is None:
            return folder
        prefix = f"{account}{ACCOUNT_FOLDER_SEPARATOR}"
        names: Dict[str, None] = {}
        try:
            tokens = await self._listing()
        except Exception:  # noqa: BLE001 - an unavailable listing must not block a read the script may still serve
            return folder
        for token in tokens:
            if token.startswith(prefix):
                names[token[len(prefix):]] = None
        if not names:
            return folder
        real_name = resolve_account_mailbox_name(account, mailbox, list(names))
        return f"{prefix}{real_name}"
