"""Mail.app UI script that archives or moves inbox messages the way a person does.

Mail's AppleScript ``move`` has no source mailbox. On a Gmail account every message belongs to All Mail and the inbox is only a label, so a scripted move adds the destination label and never removes the Inbox label, and ``move`` to All Mail does nothing. Mail's own Archive command and Message > Move to menu do remove the Inbox label, so this script drives them through System Events on a dedicated Mail viewer window that it opens, uses, and closes. Rows are matched by conversation subject because a collapsed conversation row acts on every message of the conversation in this mailbox.
"""

from __future__ import annotations

from typing import Callable

RESULT_PREFIX = "RESULT_JSON:"

ROW_SCAN_LIMIT = 40
"""Rows read per message. Each row read costs roughly 150 ms, so the scan is bounded; inbox messages that need filing sit near the top."""

SUBJECT_HANDLERS = '''
on coreSubject(subjectText)
    set cleaned to subjectText as text
    repeat
        set trimmedAny to false
        repeat with prefixText in {"re:", "fwd:", "fw:"}
            set prefixLength to length of (prefixText as text)
            if (length of cleaned) > prefixLength then
                if (text 1 thru prefixLength of cleaned) is (prefixText as text) then
                    set cleaned to text (prefixLength + 1) thru -1 of cleaned
                    repeat while (length of cleaned) > 1 and (text 1 of cleaned) is " "
                        set cleaned to text 2 thru -1 of cleaned
                    end repeat
                    set trimmedAny to true
                end if
            end if
        end repeat
        if not trimmedAny then exit repeat
    end repeat
    return cleaned
end coreSubject
'''
"""AppleScript handler shared with the receipt script so both sides compute the same conversation key. Comparison is case-insensitive because AppleScript's ``is`` ignores case by default."""

_UI_TEMPLATE = '''
use framework "Foundation"
use scripting additions

on jsonTextFor(value)
    set jsonData to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
end jsonTextFor
__SUBJECT_HANDLERS__
on newWindowId(beforeIds)
    tell application "Mail"
        set windowIds to id of windows
        repeat with candidateRef in windowIds
            set candidateId to contents of candidateRef
            if beforeIds does not contain candidateId then return candidateId
        end repeat
    end tell
    return missing value
end newWindowId

on messageTable(accountName)
    tell application "System Events"
        tell process "Mail"
            set candidates to (windows whose name contains accountName and name contains "Inbox")
            if (count of candidates) is 0 then return missing value
            return table 1 of scroll area 1 of splitter group 1 of splitter group 1 of (item 1 of candidates)
        end tell
    end tell
end messageTable

on invokeMenu(operationName, targetName, headerAccount, otherAccounts, dryRun)
    tell application "System Events"
        tell process "Mail"
            set messageMenu to menu "Message" of menu bar 1
            if operationName is "archive" then
                set archiveItem to menu item "Archive" of messageMenu
                repeat 8 times
                    if enabled of archiveItem then exit repeat
                    delay 0.15
                end repeat
                if not (enabled of archiveItem) then return "archive_unavailable"
                if dryRun then return "dry_run_ok"
                click archiveItem
                return "invoked"
            end if
            set moveItem to menu item "Move to" of messageMenu
            repeat 8 times
                if enabled of moveItem then exit repeat
                delay 0.15
            end repeat
            if not (enabled of moveItem) then return "move_unavailable"
            set subMenu to menu 1 of moveItem
            set insideAccount to false
            repeat with candidate in menu items of subMenu
                set candidateName to ""
                try
                    set candidateName to name of candidate as text
                end try
                if candidateName is headerAccount then
                    set insideAccount to true
                else if insideAccount and otherAccounts contains candidateName then
                    exit repeat
                else if insideAccount and candidateName is targetName then
                    if dryRun then return "dry_run_ok"
                    click candidate
                    return "invoked"
                end if
            end repeat
            return "target_menu_item_not_found"
        end tell
    end tell
end invokeMenu

set accountName to "__ACCOUNT__"
set operationName to "__OPERATION__"
set targetName to "__TARGET__"
set headerAccount to "__HEADER_ACCOUNT__"
set dryRun to __DRY_RUN__
set coreSubjects to {__CORES__}
set otherAccounts to {}
try
    tell application "Mail" to set otherAccounts to name of every account
end try
set rowScanLimit to __ROW_SCAN_LIMIT__
set resultRecords to {}
set viewerWindowId to missing value
set previousApp to ""
set setupError to ""

try
    tell application "System Events" to set previousApp to name of first application process whose frontmost is true
end try

try
    tell application "Mail"
        set beforeIds to id of windows
        set inboxMailbox to first mailbox of account accountName whose name is "INBOX"
        set newViewer to make new message viewer
        set selected mailboxes of newViewer to {inboxMailbox}
    end tell
    repeat 20 times
        set viewerWindowId to my newWindowId(beforeIds)
        if viewerWindowId is not missing value then exit repeat
        delay 0.25
    end repeat
    tell application "Mail" to activate
    set tableRef to missing value
    repeat 40 times
        try
            set tableRef to my messageTable(accountName)
            if tableRef is not missing value then
                tell application "System Events" to set rowTotal to count of rows of tableRef
                if rowTotal > 1 then exit repeat
            end if
        end try
        delay 0.25
    end repeat
    if tableRef is missing value then error "The Mail inbox window did not become accessible." number -1719
on error errText number errNumber
    set setupError to errText
end try

repeat with coreText in coreSubjects
    set statusText to "ui_unavailable"
    set detailText to setupError
    set matchedRow to 0
    if setupError is "" then
        set statusText to "row_not_found"
        set detailText to ""
        try
            tell application "System Events"
                set rowTotal to count of rows of tableRef
                set lastRow to rowTotal
                if lastRow > rowScanLimit then set lastRow to rowScanLimit
                repeat with scanAttempt from 1 to 2
                    repeat with rowIndex from 2 to lastRow
                        set rowTexts to {}
                        try
                            set rowTexts to value of static texts of UI element 1 of row rowIndex of tableRef
                        end try
                        if (count of rowTexts) >= 3 then
                            if (my coreSubject(item 3 of rowTexts as text)) is (coreText as text) then
                                set matchedRow to rowIndex
                                exit repeat
                            end if
                        end if
                    end repeat
                    if matchedRow > 0 then exit repeat
                    delay 1
                end repeat
                if matchedRow > 0 then
                    select row matchedRow of tableRef
                    delay 0.25
                end if
            end tell
            if matchedRow > 0 then set statusText to my invokeMenu(operationName, targetName, headerAccount, otherAccounts, dryRun)
        on error errText number errNumber
            set statusText to "ui_error"
            set detailText to errText
            if errNumber is -25211 or errText contains "assistive" then set statusText to "accessibility_denied"
        end try
    end if
    set end of resultRecords to {core_subject:(coreText as text), status:statusText, detail:detailText, row:matchedRow}
end repeat

set cleanupNotes to ""
try
    if viewerWindowId is not missing value then
        tell application "Mail" to close (first window whose id is viewerWindowId)
    else
        set cleanupNotes to "viewer window id was not detected"
    end if
on error errText
    set cleanupNotes to "viewer close failed: " & errText
end try
try
    if previousApp is not "" and previousApp is not "Mail" then tell application "System Events" to set frontmost of process previousApp to true
end try

return "RESULT_JSON:" & jsonTextFor({results:resultRecords, cleanup_notes:cleanupNotes})
'''


def build_gmail_inbox_ui_script(
    *,
    escape: Callable[[str], str],
    account_name: str,
    operation: str,
    target_name: str,
    target_account_name: str,
    core_subjects: list[str],
    dry_run: bool = False,
) -> str:
    """Return the System Events script that archives or moves the conversations named by ``core_subjects``."""
    if operation not in {"archive", "move"}:
        raise ValueError(f"Unsupported Mail UI operation: {operation}")
    quoted = lambda values: ", ".join(f'"{escape(value)}"' for value in values)  # noqa: E731
    script = _UI_TEMPLATE
    for token, value in (
        ("__SUBJECT_HANDLERS__", SUBJECT_HANDLERS),
        ("__ACCOUNT__", escape(account_name)),
        ("__OPERATION__", operation),
        ("__TARGET__", escape(target_name)),
        ("__HEADER_ACCOUNT__", escape(target_account_name or account_name)),
        ("__DRY_RUN__", "true" if dry_run else "false"),
        ("__CORES__", quoted(core_subjects)),
        ("__ROW_SCAN_LIMIT__", str(ROW_SCAN_LIMIT)),
    ):
        script = script.replace(token, value)
    return script
