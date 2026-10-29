"""Durable message lookup for Mail.app scripts.

Mail's integer ``id`` is a local row number. It is issued per mailbox, is not unique across mailboxes, and changes after a sync or a move, so a second agent working in the same inbox can invalidate it between two calls. The RFC ``Message-ID`` header (Mail's ``message id`` property, returned to callers as ``message_id``) is assigned by the sender and never changes. These handlers accept either form and use the durable one whenever the token is not a plain integer.
"""

from __future__ import annotations

MESSAGE_ID_SCAN_LIMIT = 10000
"""Mail filters by ``message id`` at roughly 0.4 ms per message, so a mailbox over this size (the unified inbox, All Mail) is refused instead of blocking Mail for minutes."""

ACCOUNT_LOOKUP_TIMEOUT_SECONDS = 4
"""Per-account bound on a message id filter. Some accounts (for example one with undownloaded headers) stall the filter, and one stalled account must not hold the whole lookup."""

_HANDLER_TEMPLATE = '''
on isMailRowId(token)
    try
        set rowNumber to token as integer
        return ((rowNumber as text) is token)
    on error
        return false
    end try
end isMailRowId

on filterByMessageToken(theMailbox, token)
    tell application "Mail"
        if my isMailRowId(token) then return (every message of theMailbox whose id is (token as integer))
        if (count of messages of theMailbox) > __MAX__ then error "This mailbox is too large to search by message id; use the integer id for it." number -1728
        return (every message of theMailbox whose message id is token)
    end tell
end filterByMessageToken

on firstMessageByToken(theMailbox, token)
    set foundMessages to my filterByMessageToken(theMailbox, token)
    if (count of foundMessages) > 0 then return item 1 of foundMessages
    return missing value
end firstMessageByToken

on findInboxMessage(token)
    tell application "Mail"
        repeat with anAccount in accounts
            try
                set candidateInbox to first mailbox of anAccount whose name is "INBOX"
                with timeout of __ACCOUNT_TIMEOUT__ seconds
                    set foundMessages to my filterByMessageToken(candidateInbox, token as text)
                end timeout
                if (count of foundMessages) > 0 then return item 1 of foundMessages
            end try
        end repeat
    end tell
    return missing value
end findInboxMessage
'''
"""Unrendered handler source; see ``MESSAGE_LOOKUP_HANDLERS``."""

MESSAGE_LOOKUP_HANDLERS = _HANDLER_TEMPLATE.replace("__MAX__", str(MESSAGE_ID_SCAN_LIMIT)).replace("__ACCOUNT_TIMEOUT__", str(ACCOUNT_LOOKUP_TIMEOUT_SECONDS))
"""AppleScript handlers shared by every Mail script that resolves a caller-supplied message identifier. ``findInboxMessage`` filters each account's INBOX, which takes about 0.1 second, instead of the unified inbox, which takes about 2 seconds per message."""
