"""Outlook AppleScript composition script generation."""

import logging
from typing import Callable

from ...email_models import EmailRequest

logger = logging.getLogger(__name__)


class OutlookCompositionScripts:
    """Generate Outlook AppleScript for draft composition and replies."""

    def __init__(self, escape: Callable[[str], str]):
        self._escape = escape

    def compose_email_script(self, email_request: EmailRequest, draft_only: bool = True) -> str:
        """Generate AppleScript to compose a new email draft in Microsoft Outlook."""
        subject = self._escape(email_request.subject)
        body = self._escape(email_request.body)
        to_recipient_lines = self.recipient_applescript_lines([email_request.recipient], "to")
        cc_recipient_lines = self.recipient_applescript_lines(email_request.cc, "cc")
        bcc_recipient_lines = self.recipient_applescript_lines(email_request.bcc, "bcc")

        script = f'''
        tell application "Microsoft Outlook"
            set newMessage to make new outgoing message with properties {{¬
                subject:"{subject}", ¬
                plain text content:"{body}"}}

            -- Add recipient using correct syntax
            {to_recipient_lines}

            {cc_recipient_lines}

            {bcc_recipient_lines}

            -- CRITICAL: Open the draft to make it visible
            open newMessage

            activate
        end tell
        '''

        return script

    def recipient_applescript_lines(self, recipients: list[str], recipient_type: str) -> str:
        """Generate Outlook AppleScript recipient creation lines."""
        if not recipients:
            return ""

        recipient_classes = {
            "to": "to recipient",
            "cc": "cc recipient",
            "bcc": "bcc recipient",
        }
        recipient_class = recipient_classes[recipient_type]

        lines = []
        for recipient in recipients:
            recipient_address = self._escape(recipient)
            recipient_name = self._escape(recipient.split("@", 1)[0] if "@" in recipient else recipient)
            lines.append(f'''make new {recipient_class} at newMessage with properties {{¬
                email address:{{name:"{recipient_name}", address:"{recipient_address}"}}}}''')

        return "\n\n            ".join(lines)

    def send_email_script(self, email_request: EmailRequest) -> str:
        """Fail closed: Outlook automation never sends email directly."""
        return '''
        tell application "Microsoft Outlook"
            return "ERROR: Direct sending is disabled. Create a visible draft for manual review instead."
        end tell
        '''

    def reply_to_email_script(self, email_id: str, reply_body: str, reply_all: bool = True, draft_only: bool = True) -> str:
        """
        Generate AppleScript to create a reply draft in Outlook using its
        native ``reply to`` command.

        Verb form
        ---------
        Outlook's AppleScript dictionary exposes the reply verb as
        ``reply to`` (NOT ``reply`` or ``reply all`` as bare verbs --
        those bare forms produce ``-2741: Expected end of line, etc.
        but found identifier`` at parse time, which historically
        bounced into this script's ``on error`` block and surfaced to
        the agent as a generic draft-creation failure). The verb takes
        two named parameters that matter for us:

          * ``reply to all`` (boolean, default ``false``) -- whether to
            include every recipient of the original message.
          * ``opening window`` (boolean, default ``true``) -- whether
            Outlook should pop the draft into a new editor window.

        Why we let the draft window open
        --------------------------------
        We explicitly do NOT pass ``opening window false`` here even
        though doing so would (in principle) suppress the focus-stealing
        draft window. Live osascript probing against Outlook for Mac on
        May 22, 2026 showed that ``reply to originalMessage opening
        window false`` hangs indefinitely (osascript never returns,
        Outlook's outgoing-message pipeline wedges, subsequent
        ``make new outgoing message`` calls then also hang until the
        app is force-quit). With the parameter at its default ``true``
        the verb returns cleanly in roughly 40s on this account, the
        draft lands in the Drafts folder, and a draft window appears
        briefly.

        We accept that window-appearance trade-off in exchange for the
        ability to reliably create the draft at all. We still do not
        call ``activate`` on the application after the verb, so
        Outlook is not forcibly raised to the foreground -- the
        draft window appears wherever Outlook is in the window order,
        rather than yanking the user out of whatever they were doing.

        Hang avoidance (May 14 rule applied to replies)
        -----------------------------------------------
        The new-draft compose path was previously hardened against the
        well-documented Outlook-for-Mac AppleEvent hang by treating
        ``plain text content`` / recipient readback from an unsent
        outgoing message as a forbidden validation target
        ([Outlook Draft AppleScript Hang Fix](a4eb5a7d-0299-44a6-8a58-a594476031ad)).
        The reply path now follows the same rule:

          * No ``set originalContent to plain text content of replyMessage``
            (readback against an unsent draft is the canonical hang).
          * No ``open replyMessage`` (focus-stealing round-trip; the
            ``reply to`` verb's default ``opening window true`` already
            opens the draft window, so a separate ``open`` is also
            redundant).
          * No ``activate`` on the application (focus-steal, and an
            additional round-trip).
          * Trade-off: the in-body quoted thread that Outlook would
            otherwise interpolate is overwritten by the agent's reply
            body. Recipients, In-Reply-To, References, and subject
            prefixing all still come from Outlook's native ``reply to``
            command and remain intact.
        """
        escaped_body = self._escape(reply_body)
        escaped_email_id = self._escape(email_id)

        # ``reply to all`` is a boolean parameter on the ``reply to``
        # verb, not a separate verb. ``true``/``false`` literals are
        # the AppleScript-native form.
        reply_to_all_literal = "true" if reply_all else "false"

        script = f'''
        tell application "Microsoft Outlook"
            try
                -- Find the original message by ID. Read-only access to an
                -- existing inbox message is not subject to the unsent-draft
                -- AppleEvent hang, so this lookup is safe.
                set originalMessage to (first message whose id is "{escaped_email_id}")

                -- Create reply using Outlook's ``reply to`` verb.
                -- ``opening window`` is intentionally left at its
                -- default (true): passing ``opening window false``
                -- hangs the verb indefinitely on Outlook for Mac
                -- (validated live May 22, 2026). Outlook will pop a
                -- draft window for this message; we do NOT call
                -- ``activate`` after the verb, so the application is
                -- not forcibly raised to the foreground. Recipients,
                -- threading headers, and subject prefix come from
                -- Outlook's native handling of the verb.
                set replyMessage to reply to originalMessage reply to all {reply_to_all_literal}

                -- Write the agent's body directly. We do NOT first read
                -- ``plain text content of replyMessage`` to prepend to
                -- the quoted thread, because that readback is the
                -- canonical Outlook unsent-draft hang. The trade-off is
                -- that the in-body quote of the original is overwritten;
                -- recipients and threading headers are unaffected.
                set plain text content of replyMessage to "{escaped_body}"

                -- Validate by script completion + Drafts-folder presence.
                -- We deliberately do NOT enumerate properties of
                -- replyMessage after writing it: any such readback is
                -- the documented Outlook-for-Mac AppleEvent hang.
                return "SUCCESS: Reply draft created"

            on error errMsg
                return "ERROR: " & errMsg
            end try
        end tell
        '''

        logger.info(f"📧 Generated Outlook reply script for email_id={email_id[:20]}..., reply_all={reply_all}, draft_only={draft_only}")

        return script
