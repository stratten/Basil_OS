"""Bounded Mail search, quoted-history folding, and body-read timeouts, all without touching Mail."""

import shutil
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailData,
    EmailDataList,
    EmailSearchCriteria,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_retrieval import (
    EmailRetrievalMixin,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mail_app_service import (
    MailAppService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.quoted_history import (
    OMITTED_NOTE_TEMPLATE,
    fold_quoted_history,
    split_quoted_history,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.retrieval_scripts import (
    BODY_NOT_DOWNLOADED_MARKER,
    BODY_READ_TIMEOUT_SECONDS,
    SELECTIVE_SEARCH_MAX_MAILBOX_MESSAGES,
)


def test_selective_search_supports_sender_and_subject_in_inbox_or_a_named_mailbox():
    service = MailAppService()
    assert service.supports_selective_search("inbox", EmailSearchCriteria(sender="a.soroka@healmind.com"))
    assert service.supports_selective_search("Work / INBOX", EmailSearchCriteria(subject_contains="invoice"))
    assert service.supports_selective_search("INBOX", EmailSearchCriteria(sender="a.soroka@healmind.com"))


@pytest.mark.parametrize(
    "folder, criteria",
    [
        ("inbox", None),
        ("inbox", EmailSearchCriteria(sender="com")),
        ("inbox", EmailSearchCriteria(is_read=False)),
        ("inbox", EmailSearchCriteria(sender="a.soroka@healmind.com", body_contains="sow")),
        ("inbox", EmailSearchCriteria(sender="a.soroka@healmind.com", has_attachments=True)),
        ("Sent", EmailSearchCriteria(sender="a.soroka@healmind.com")),
    ],
)
def test_selective_search_declines_broad_body_attachment_and_special_folder_searches(folder, criteria):
    assert not MailAppService().supports_selective_search(folder, criteria)


def test_search_script_filters_inside_mail_per_account_inbox_and_reads_only_the_limit():
    script = MailAppService().search_emails_script("inbox", 15, EmailSearchCriteria(sender='a.soroka@healmind.com'))
    assert 'first mailbox of anAccount whose name is "INBOX"' in script
    assert '(sender contains "a.soroka@healmind.com"))' in script
    assert "messages of aMailbox whose (date received >= date " in script
    assert "if takenCount >= 15 then exit repeat" in script
    assert f"(count of messages of aMailbox) > {SELECTIVE_SEARCH_MAX_MAILBOX_MESSAGES} then" in script
    assert "content of aMessage" not in script
    assert "messages of inbox" not in script
    assert "strategy=account_mailbox_filter" in script
    assert 'coverageReason to "mailbox_too_large_to_filter"' in script


def test_search_script_for_a_named_mailbox_uses_name_filter_and_reports_a_missing_mailbox():
    script = MailAppService().search_emails_script(
        "Work / Clients", 5, EmailSearchCriteria(subject_contains="invoice", date_from=datetime(2026, 1, 2))
    )
    assert 'first mailbox of account "Work" whose name is "Clients"' in script
    assert 'whose (date received >= date "Friday, January 02, 2026 at 12:00:00 AM") and (subject contains "invoice")' in script
    assert 'coverageReason to "mailbox_unavailable"' in script


def test_search_script_escapes_quotes_in_search_terms():
    script = MailAppService().search_emails_script("inbox", 5, EmailSearchCriteria(sender='o"brien@x.com'))
    assert 'sender contains "o\\"brien@x.com"' in script


@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is only available on macOS")
@pytest.mark.parametrize("folder", ["inbox", "Work / Clients"])
def test_search_and_expand_scripts_compile_without_executing(tmp_path, folder):
    service = MailAppService()
    scripts = {
        "search": service.search_emails_script(folder, 10, EmailSearchCriteria(sender="a.soroka@healmind.com")),
        "expand": service.expand_email_details_script(folder, ["1", "2"], 4000),
    }
    for name, script in scripts.items():
        source = tmp_path / f"{name}.applescript"
        source.write_text(script)
        completed = subprocess.run(
            ["osacompile", "-o", str(tmp_path / f"{name}.scpt"), str(source)], capture_output=True, text=True, timeout=60
        )
        assert completed.returncode == 0, completed.stderr


def test_expand_script_bounds_the_body_read_and_returns_a_retry_marker():
    script = MailAppService().expand_email_details_script("inbox", ["1"], 4000)
    assert f"with timeout of {BODY_READ_TIMEOUT_SECONDS} seconds" in script
    assert f'set fullContent to "{BODY_NOT_DOWNLOADED_MARKER}"' in script


NEWEST = "Hi Stratten,\nIs there anything further you need from me to get the project started?"


def test_quoted_history_is_cut_at_an_on_date_wrote_attribution():
    body = f"{NEWEST}\n\nOn Mon, Oct 26, 2026 at 12:03PM Avigail Soroka <a.soroka@healmind.com> wrote:\nHi Stratten,\nI have forwarded our information."
    newest, omitted = split_quoted_history(body)
    assert newest == NEWEST
    assert omitted == len(body) - len(NEWEST)


def test_quoted_history_handles_a_wrapped_attribution_original_message_and_outlook_headers():
    wrapped = f"{NEWEST}\n\nOn Monday, October 26, 2026 at 12:03 PM, Avigail Soroka <a.soroka@healmind.com>\nwrote:\nearlier"
    assert split_quoted_history(wrapped)[0] == NEWEST
    original = f"{NEWEST}\n\n-----Original Message-----\nFrom: A\nSent: B\nTo: C\nearlier"
    assert split_quoted_history(original)[0] == NEWEST
    outlook = f"{NEWEST}\n\n________________________________\nFrom: Avigail Soroka\nSent: Monday, October 26, 2026 12:03 PM\nTo: Stratten\nSubject: Salesforce\n\nearlier"
    assert split_quoted_history(outlook)[0] == NEWEST
    quoted = f"{NEWEST}\n\n> earlier line\n> another\n"
    assert split_quoted_history(quoted)[0] == NEWEST


def test_quoted_history_keeps_text_without_history_and_text_that_starts_with_history():
    plain = "On Monday we plan to start.\nThanks."
    assert split_quoted_history(plain) == (plain, 0)
    starts_quoted = "On Mon, Oct 26, 2026 Avigail wrote:\nonly quoted text"
    assert split_quoted_history(starts_quoted) == (starts_quoted, 0)
    assert split_quoted_history("") == ("", 0)
    mid_sentence = "Please send it.\nHe said: From: now on we use the portal.\nThanks."
    assert split_quoted_history(mid_sentence) == (mid_sentence, 0)


def test_fold_adds_a_note_with_the_omitted_size():
    body = f"{NEWEST}\n\nOn Mon, Oct 26, 2026 Avigail Soroka wrote:\nearlier text"
    folded = fold_quoted_history(body)
    assert folded.startswith(NEWEST)
    assert folded.endswith(OMITTED_NOTE_TEMPLATE.format(count=len(body) - len(NEWEST)))
    assert fold_quoted_history(NEWEST) == NEWEST


class _Retrieval(EmailRetrievalMixin):
    def __init__(self, bodies):
        self._bodies = bodies
        self.applescript_service = SimpleNamespace(expand_email_details_via_applescript=self._expand)

    def _get_client_by_name(self, client_name=None):
        return SimpleNamespace(name="Mail", automation_method="applescript")

    async def _resolve_mail_folder(self, selected_client, folder):
        return folder

    async def _expand(self, client_name, ids, folder, excerpt_chars):
        return [
            EmailData(id=email_id, subject="s", sender="a", recipient="b", content=body, date_sent=datetime(2026, 10, 27), is_read=True)
            for email_id, body in zip(ids, self._bodies)
        ]


@pytest.mark.asyncio
async def test_expand_folds_quoted_history_by_default_and_keeps_it_on_request():
    body = f"{NEWEST}\n\nOn Mon, Oct 26, 2026 Avigail Soroka wrote:\nearlier text"
    service = _Retrieval([body])
    folded = await service.expand_email_details(["1"])
    assert folded[0].content.startswith(NEWEST) and "Quoted earlier messages omitted" in folded[0].content
    kept = await service.expand_email_details(["1"], include_quoted_history=True)
    assert kept[0].content == body


class _SearchService(EmailRetrievalMixin):
    def __init__(self, selective):
        self.calls = []
        mail = SimpleNamespace(supports_selective_search=lambda folder, criteria: selective)
        self.applescript_service = SimpleNamespace(
            mail_app_service=mail,
            search_emails_via_applescript=self._selective,
            get_emails_via_applescript=self._legacy,
        )

    async def _selective(self, client, folder, limit, criteria):
        self.calls.append("selective")
        return EmailDataList([], coverage_metadata={"strategy": "account_mailbox_filter"})

    async def _legacy(self, client, folder, limit, criteria):
        self.calls.append("legacy")
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("selective, expected", [(True, "selective"), (False, "legacy")])
async def test_search_routes_selective_searches_to_the_in_mail_filter(selective, expected):
    service = _SearchService(selective)
    result = await service._search_emails_via_applescript(
        EmailSearchCriteria(sender="a.soroka@healmind.com"), 15, SimpleNamespace(name="Mail", automation_method="applescript")
    )
    assert service.calls == [expected]
    assert result.coverage_metadata == {"strategy": "account_mailbox_filter"} if selective else result == []
