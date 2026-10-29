"""Who a Gmail reply goes to.

Replying to everyone is the normal default, as it is in Mail.app and Outlook: the sender (or their Reply-To address) and the other To recipients go in To, and the original Cc recipients stay in Cc. The user's own addresses are never added, and an address appears once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple

from .message_shaping import bare_addresses


@dataclass(frozen=True)
class ReplyRecipients:
    to: Tuple[str, ...]
    cc: Tuple[str, ...]


def _unique(addresses: Iterable[str], excluded: Set[str]) -> List[str]:
    seen: Set[str] = set(excluded)
    kept: List[str] = []
    for address in addresses:
        if address and address not in seen:
            seen.add(address)
            kept.append(address)
    return kept


def plan_reply_recipients(
    *,
    from_header: str,
    reply_to_header: str,
    to_header: str,
    cc_header: str,
    own_addresses: Set[str],
    reply_all: bool,
) -> ReplyRecipients:
    """Return the To and Cc addresses for a reply to a message with these headers.

    ``own_addresses`` are lower-cased addresses that belong to the user. When the original was sent by the user, the reply goes to the people it was sent to, because answering yourself would only address you.
    """
    own = {address.lower() for address in own_addresses}
    sender = bare_addresses(reply_to_header or from_header)
    original_to = bare_addresses(to_header)
    original_cc = bare_addresses(cc_header)

    from_me = bool(sender) and all(address in own for address in sender)
    if from_me:
        primary = _unique(original_to, own)
        copied = _unique(original_cc, own | set(primary)) if reply_all else []
        if not primary and copied:
            primary, copied = copied, []
        return ReplyRecipients(to=tuple(primary), cc=tuple(copied))

    primary = _unique(sender, own)
    if not reply_all:
        return ReplyRecipients(to=tuple(primary), cc=())
    primary = _unique([*primary, *original_to], own)
    copied = _unique(original_cc, own | set(primary))
    return ReplyRecipients(to=tuple(primary), cc=tuple(copied))
