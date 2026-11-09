"""Labeled cases for the Quick Assist context classifier: browsers and web apps.

Browsers always fall back to OCR pattern matching, in a fixed order (email, social media, document, code). These cases include true positives and the pages most likely to be misclassified because of broad patterns: menu words such as View and Insert, bullet lists, email addresses in a footer, and the word Draft.

Same tuple layout as ``quick_assist_cases_native``: (case_id, app_name, ocr_text, expected, group, judgment_note).
"""

from __future__ import annotations

from typing import List

from quick_assist_cases_native import Case

GMAIL = "Compose\nNew Message\nTo: lena.ortiz@example.com\nSubject: Updated agenda\nHi Lena,\nSending the agenda for Thursday."
GMAIL_THREAD = "Inbox  Starred  Sent\nRe: Budget review\nFrom: Chris Park\nOn Fri, Oct 30 Chris wrote:\n> Can we move to Monday?\nReply  Forward"
OWA = "New message\nTo\nCc\nBcc\nSubject\nAdd a subject\nSend  Discard  Draft saved"
GDOCS = "Untitled document\nFile  Edit  View  Insert  Format  Tools  Extensions  Help\nTitle\nHeading 1\nThe plan has three phases."
NOTION_WEB = "Untitled\nType '/' for commands\n- Launch checklist\n- Pricing page copy\n1. Draft announcement"
X_COMPOSE = "What's happening?\nCharacters remaining: 280\nPost\nx.com/home"
X_REPLY = "Post your reply\nReply to @tobias_k\nx.com/tobias_k/status/1\nCharacters remaining: 250"
LINKEDIN = "Start a post\nlinkedin.com/feed\nWhat do you want to talk about?\nShare your thoughts"
REDDIT = "reddit.com/r/macapps\nr/macapps\nCreate Post\nupvote  downvote\nWhat are your thoughts?\nComment"
GITHUB_PR = "Pull Request #482\nFiles changed 6\ndef parse_event(payload):\n    return payload['id']\n+import json\nMerge pull request  GitHub"
STACKOVERFLOW = "stackoverflow.com\nHow do I read a file in Python?\nwith open('x.txt') as f:\n    data = f.read()\nTraceback (most recent call last):"
JIRA = "PROJ-412  Fix login redirect\nStatus: In Progress\nDescription\nUsers are redirected to the wrong page after login.\nAdd a comment"
ARTICLE_BULLETS = "How to choose a standing desk\n- Check the height range\n- Look at the motor noise\n- Compare warranty terms\n1. Measure your space\n2. Set a budget"
SHOP_PAGE = "Wireless Headphones\nSize  Color\nView details\nAdd to cart\nReviews (412)\nFont  Tools  Insert coupon"
NEWS_FOOTER = "City council approves transit plan\nThe council voted 7 to 2 on Tuesday.\nContact: tips@newsroom.example.com\nAbout  Careers  Privacy"
DOC_WEB_EMAIL = "Project brief\nPage 1 of 3\nContact the owner at owner@example.com for access.\nHeading 1\nGoals"
SLACK_WEB = "slack.com\n# launch-prep\nAli 3:12 PM\nDid the build finish?\nMessage #launch-prep"
WA_WEB = "web.whatsapp.com\nType a message\nSam\nsee you at 6"
SHEETS = "Sheet1\nFile Edit View Insert Format Data Tools\nA1 Region  B1 Q3\nA2 West  B2 412"
GENERIC_FORM = "Contact us\nName\nPhone\nMessage\nSubmit"
DRAFT_BLOG = "Draft\nBlog editor\nTitle\nWrite your post here\nPublish  Preview"
CODE_NO_KEYWORDS = "Build Output\nCompiling module core\nWarning: unused variable\nBuild succeeded"

BROWSER_CASES: List[Case] = [
    ("web-01", "Safari", GMAIL, "email", "web_true_positive", ""),
    ("web-02", "Google Chrome", GMAIL_THREAD, "email", "web_true_positive", ""),
    ("web-03", "Microsoft Edge", OWA, "email", "web_true_positive", ""),
    ("web-04", "Google Chrome", GDOCS, "document", "web_true_positive", ""),
    ("web-05", "Safari", NOTION_WEB, "document", "web_true_positive", ""),
    ("web-06", "Google Chrome", X_COMPOSE, "social_media", "web_true_positive", ""),
    ("web-07", "Safari", X_REPLY, "social_media", "web_true_positive", ""),
    ("web-08", "Firefox", LINKEDIN, "social_media", "web_true_positive", ""),
    ("web-09", "Arc", REDDIT, "social_media", "web_true_positive", ""),
    ("web-10", "Google Chrome", GITHUB_PR, "code", "web_true_positive", ""),
    ("web-11", "Safari", STACKOVERFLOW, "code", "web_true_positive", ""),
    ("web-12", "Google Chrome", JIRA, "other", "web_ambiguous", "ticket comment: no specialized enhancer fits"),
    ("web-13", "Safari", ARTICLE_BULLETS, "other", "web_false_positive_risk", "read-only article with bullets"),
    ("web-14", "Google Chrome", SHOP_PAGE, "other", "web_false_positive_risk", "menu-like words on a shopping page"),
    ("web-15", "Safari", NEWS_FOOTER, "other", "web_false_positive_risk", "an email address in a footer"),
    ("web-16", "Google Chrome", DOC_WEB_EMAIL, "document", "web_false_positive_risk", "document that mentions an email address"),
    ("web-17", "Google Chrome", SLACK_WEB, "other", "web_ambiguous", "chat reply in the browser"),
    ("web-18", "Safari", WA_WEB, "other", "web_ambiguous", "chat reply in the browser"),
    ("web-19", "Google Chrome", SHEETS, "other", "web_ambiguous", "spreadsheet; no enhancer, but menu words match document"),
    ("web-20", "Safari", GENERIC_FORM, "other", "web_ambiguous", "plain web form"),
    ("web-21", "Google Chrome", DRAFT_BLOG, "document", "web_ambiguous", "blog editor"),
    ("web-22", "Google Chrome", CODE_NO_KEYWORDS, "code", "web_ambiguous", "build log without language keywords"),
    ("web-23", "Brave Browser", GMAIL, "email", "web_true_positive", ""),
    ("web-24", "Orion", GMAIL, "email", "web_unlisted_browser", "Orion is not in the browser list but falls back to OCR anyway"),
    ("web-25", "Dia", X_COMPOSE, "social_media", "web_unlisted_browser", "Dia is not in the browser list but falls back to OCR anyway"),
]
