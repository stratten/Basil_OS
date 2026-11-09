"""Labeled cases for the Quick Assist context classifier: native apps.

Each case is (case_id, app_name, ocr_text, expected, group, judgment_note). ``expected`` is the context type a reasonable person would want: email, social_media, document, code, or other (no specialized enhancer). ``judgment_note`` is non-empty when the label is a judgment call, so those rows are reported separately.

The OCR text is hand-written to resemble what Tesseract returns for the window, including menu bars and chrome. It is synthetic: it bounds how well the classifier generalizes, it does not replace a sample of real screens.
"""

from __future__ import annotations

from typing import List, Tuple

Case = Tuple[str, str, str, str, str, str]

MAIL_COMPOSE = "New Message\nTo: dana.reyes@example.com\nCc:\nSubject: Q4 renewal timeline\nHi Dana,\nFollowing up on our call about the renewal."
OUTLOOK_REPLY = "Reply  Reply All  Forward\nFrom: Priya Nair <priya@example.org>\nTo: Sam Lee\nSubject: RE: Vendor onboarding\nOn Mon, Oct 26 Priya wrote:\n> Can you confirm the start date?"
SWIFT_CODE = "struct RecorderView: View {\n    let session: Session\n    var body: some View {\n        Text(session.title)\n    }\n}\nimport SwiftUI\nLine 14:5"
PY_CODE = "import asyncio\nfrom pathlib import Path\n\nasync def main():\n    path = Path('data')\n    print(path)\n\nTraceback (most recent call last):"
WORD_DOC = "Page 2 of 9\nWords: 2,481\nFile Edit View Insert Format Tools\nHeading 1\nThe committee reviewed the proposal and recommended a phased rollout."
NOTES_DOC = "Grocery list\n- eggs\n- spinach\n- oat milk\nMeeting notes\n1. Review budget\n2. Confirm hiring plan"
CHAT_REPLY = "# design-review\nMaya  10:42 AM\nCan someone look at the onboarding mock before standup?\nMessage #design-review"
IMESSAGE = "Messages\nJordan\nare we still on for dinner tonight?\niMessage\nSend"
TERMINAL = "strattenwaldt@mac basil % git status\nOn branch main\nChanges not staged for commit:\n  modified: README.md\nstrattenwaldt@mac basil % npm run build"
TWEET_APP = "What's happening?\nCharacters remaining: 214\nReply to @sara_dev's tweet\nPost"
PRESENTATION = "Slide 4 of 12\nQuarterly results\nRevenue up 18%\nFont  Size  Bold  Italic"
CALENDAR = "Calendar\nTuesday, Nov 3\n10:00 AM Standup\n2:00 PM Roadmap review\nNew Event"
SPREADSHEET = "Sheet1\nA1  Region  B1  Q3  C1  Q4\nA2  West  B2  412  C2  498"

NATIVE_CASES: List[Case] = [
    ("nat-01", "Mail", MAIL_COMPOSE, "email", "native_listed", ""),
    ("nat-02", "Microsoft Outlook", OUTLOOK_REPLY, "email", "native_listed", ""),
    ("nat-03", "Spark", OUTLOOK_REPLY, "email", "native_listed", ""),
    ("nat-04", "Xcode", SWIFT_CODE, "code", "native_listed", ""),
    ("nat-05", "Visual Studio Code", PY_CODE, "code", "native_listed", ""),
    ("nat-06", "Cursor", PY_CODE, "code", "native_listed", ""),
    ("nat-07", "Terminal", TERMINAL, "code", "native_listed", ""),
    ("nat-08", "iTerm2", TERMINAL, "code", "native_listed", ""),
    ("nat-09", "Microsoft Word", WORD_DOC, "document", "native_listed", ""),
    ("nat-10", "Pages", WORD_DOC, "document", "native_listed", ""),
    ("nat-11", "Obsidian", NOTES_DOC, "document", "native_listed", ""),
    ("nat-12", "Twitter", TWEET_APP, "social_media", "native_listed", ""),
    ("nat-13", "Code", PY_CODE, "code", "native_unlisted", "VS Code reports its process name as Code"),
    ("nat-14", "Notes", NOTES_DOC, "document", "native_unlisted", ""),
    ("nat-15", "Zed", PY_CODE, "code", "native_unlisted", ""),
    ("nat-16", "Sublime Merge", SWIFT_CODE, "code", "native_unlisted", ""),
    ("nat-17", "Mimestream", MAIL_COMPOSE, "email", "native_unlisted", ""),
    ("nat-18", "Superhuman", OUTLOOK_REPLY, "email", "native_unlisted", ""),
    ("nat-19", "Canary Mail", MAIL_COMPOSE, "email", "native_unlisted", ""),
    ("nat-20", "Microsoft PowerPoint", PRESENTATION, "document", "native_unlisted", ""),
    ("nat-21", "Keynote", PRESENTATION, "document", "native_unlisted", ""),
    ("nat-22", "Xcode-beta", SWIFT_CODE, "code", "native_unlisted", "A beta Xcode build reports a different name"),
    ("nat-23", "Slack", CHAT_REPLY, "other", "chat_apps", "chat reply, no document structure; current mapping treats chat as document"),
    ("nat-24", "Discord", CHAT_REPLY, "other", "chat_apps", "chat reply; current mapping treats chat as document"),
    ("nat-25", "Messages", IMESSAGE, "other", "chat_apps", "chat reply; app is not listed"),
    ("nat-26", "WhatsApp", IMESSAGE, "other", "chat_apps", "chat reply; current mapping treats chat as document"),
    ("nat-27", "Microsoft Teams", CHAT_REPLY, "other", "chat_apps", "chat reply; app is not listed"),
    ("nat-28", "Calendar", CALENDAR, "other", "non_writing_apps", ""),
    ("nat-29", "Numbers", SPREADSHEET, "other", "non_writing_apps", ""),
    ("nat-30", "", MAIL_COMPOSE, "email", "no_app_name", ""),
    ("nat-31", "unknown", SWIFT_CODE, "code", "no_app_name", ""),
]
