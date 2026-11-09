"""Allow and deny corpora for the conservative AppleScript read-only classifier."""

import pytest

from api.services.agent_processing.tools.safety.applescript_read_only_classifier import classify_applescript_read_only
from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor

_ASSESSOR = RiskAssessor()


def _classify(script: str):
    return classify_applescript_read_only(script, _ASSESSOR.is_read_only_command)


ALLOWED = {
    "inline tell get": 'tell application "Mail" to get subject of every message of inbox',
    "block tell with variable": (
        'tell application "Mail"\n'
        "  set theMessages to messages of inbox\n"
        "  return count of theMessages\n"
        "end tell"
    ),
    "calendar events with start date": (
        'tell application "Calendar"\n'
        "  set todaysEvents to every event of calendar 1 whose start date is greater than (current date)\n"
        "  return summary of todaysEvents\n"
        "end tell"
    ),
    "repeat over a list": (
        'tell application "Notes"\n'
        "  set noteTitles to {}\n"
        "  repeat with aNote in every note\n"
        "    log name of aNote\n"
        "  end repeat\n"
        "end tell"
    ),
    "try with error handler": (
        "try\n"
        '  tell application "Finder" to get name of every file of desktop\n'
        "on error errMsg\n"
        "  return errMsg\n"
        "end try"
    ),
    "comments and continuation": (
        "-- list the inbox\n"
        '(* block\n comment *) tell application "Mail" to ¬\n'
        "  get subject of first message of inbox\n"
    ),
    "if then else": (
        "set messageCount to 3\n"
        "if messageCount > 2 then\n"
        '  return "many"\n'
        "else\n"
        '  return "few"\n'
        "end if"
    ),
    "do shell script that is read-only": 'do shell script "ls -la ~/Desktop"',
    "set from a read-only shell script": 'set listing to do shell script "cat /etc/hosts"',
    "verb words only inside string literals": 'tell application "Mail" to get (count of (messages of inbox whose subject contains "delete send open"))',
    "with timeout": 'with timeout of 30 seconds\n  tell application "Mail" to get name of inbox\nend timeout',
}

DENIED = {
    "empty": "",
    "whitespace only": "   \n  ",
    "mail send": 'tell application "Mail" to send (make new outgoing message with properties {subject:"x"})',
    "delete a message": 'tell application "Mail"\n  delete (first message of inbox)\nend tell',
    "move a message": 'tell application "Mail" to move (first message of inbox) to mailbox "Archive"',
    "make a calendar event": 'tell application "Calendar" to make new event at end of events of calendar 1',
    "set an application property": 'tell application "Mail" to set read status of (first message of inbox) to true',
    "set an unknown bare name inside a tell": 'tell application "Finder"\n  set name to "x"\nend tell',
    "set a lowercase property inside a tell": 'tell application "Finder"\n  set selection to desktop\nend tell',
    "set clipboard": 'set the clipboard to "x"',
    "set volume": "set volume 3",
    "activate": 'tell application "Mail" to activate',
    "quit": 'tell application "Mail" to quit',
    "open file": 'tell application "Finder" to open file "x" of desktop',
    "keystroke through System Events": 'tell application "System Events" to keystroke "a"',
    "System Events read": 'tell application "System Events" to get name of every process',
    "unlisted application": 'tell application "Terminal" to get name',
    "tell by id": 'tell application id "com.apple.mail" to get name',
    "tell a non-application": "tell me to get name",
    "do shell script with rm": 'do shell script "rm -rf ~/Desktop/x"',
    "do shell script with redirection": 'do shell script "ls > /tmp/out.txt"',
    "do shell script with pipe to a writer": 'do shell script "cat file | tee out"',
    "do shell script with concatenation": 'do shell script "ls " & quoted form of "x"',
    "do shell script with administrator privileges": 'do shell script "ls" with administrator privileges',
    "set from a mutating shell script": 'set out to do shell script "mv a b"',
    "run script": 'run script "return 1"',
    "load script": 'load script file "x"',
    "write to a file": 'set f to open for access file "x" with write permission',
    "display dialog": 'display dialog "hi"',
    "delay is fine but say is not": 'say "hello"',
    "handler definition": "on doThing()\n  return 1\nend doThing",
    "unterminated string": 'tell application "Mail" to get "abc',
    "unterminated comment": "(* never closed\nreturn 1",
    "unclosed tell": 'tell application "Mail"\n  return 1',
    "stray end": "end tell",
    "mismatched end": 'tell application "Mail"\n  return 1\nend repeat',
    "raw event code": 'tell application "Mail" to «event aevtodoc»',
    "inline tell that opens a block": 'tell application "Mail" to tell application "Finder"',
    "log out": "log out",
    "bare expression that is not a known read form": 'tell application "Mail" to check for new mail',
    "trash": 'tell application "Finder" to delete (every file of trash)',
    "verb hidden after set": 'tell application "Mail"\n  set theResult to (make new outgoing message)\nend tell',
    "repeat with mutation": 'tell application "Mail"\n  repeat with aMessage in messages of inbox\n    delete aMessage\n  end repeat\nend tell',
    "line continuation hiding a verb": 'tell application "Mail" to get ¬\n subject of (make new outgoing message)',
}


@pytest.mark.parametrize("name", sorted(ALLOWED))
def test_recognized_read_only_scripts_are_allowed(name):
    verdict = _classify(ALLOWED[name])

    assert verdict.is_read_only is True, verdict.reason


@pytest.mark.parametrize("name", sorted(DENIED))
def test_anything_that_changes_state_or_cannot_be_proven_is_denied(name):
    verdict = _classify(DENIED[name])

    assert verdict.is_read_only is False, f"{name} was wrongly allowed"
    assert verdict.reason


def test_a_denial_names_the_offending_line():
    verdict = _classify('tell application "Mail"\n  delete (first message of inbox)\nend tell')

    assert "delete" in verdict.reason


def test_non_string_input_is_denied_rather_than_raising():
    assert _classify(None).is_read_only is False  # type: ignore[arg-type]
    assert _classify(42).is_read_only is False  # type: ignore[arg-type]


def test_a_very_long_script_is_classified_without_error():
    script = 'tell application "Mail"\n' + "\n".join(f"  set value{index} to count of messages of inbox" for index in range(2000)) + "\nend tell"

    assert _classify(script).is_read_only is True


def test_special_characters_in_strings_do_not_confuse_the_parser():
    script = 'tell application "Mail" to get (count of (messages of inbox whose subject contains "a \\" -- # (* quote"))'

    assert _classify(script).is_read_only is True


DATE_PART_ALLOWED = {
    "midnight on a date the script created": (
        "set d0 to current date\n"
        "set time of d0 to 0\n"
        "return d0"
    ),
    "midnight inside a tell block": (
        'tell application "Calendar"\n'
        "  set d0 to current date\n"
        "  set time of d0 to 0\n"
        "  return summary of every event whose start date is greater than d0\n"
        "end tell"
    ),
    "an hour on a date literal": (
        'set d0 to date "Monday, January 1, 2024 12:00:00 AM"\n'
        "set hours of d0 to 9\n"
        "return d0"
    ),
    "a part set from arithmetic": (
        "set d0 to (current date)\n"
        "set day of d0 to (day of d0) - 1\n"
        "return d0"
    ),
}

DATE_PART_DENIED = {
    "a variable the script never assigned from a date": "set time of d0 to 0\nreturn d0",
    "a part of an application object": 'tell application "Mail"\n  set day of m1 to 3\nend tell',
    "a property that is not a date part": 'tell application "Mail"\n  set d0 to current date\n  set read status of d0 to true\nend tell',
    "a variable reassigned away from a date": "set d0 to current date\nset d0 to 5\nset time of d0 to 0\nreturn d0",
    "a date taken from an application object": (
        'tell application "Calendar"\n'
        "  set d0 to start date of event 1\n"
        "  set time of d0 to 0\n"
        "end tell"
    ),
    "a mutating command inside the new value": 'set d0 to current date\nset time of d0 to (do shell script "rm /tmp/x")\nreturn d0',
}


@pytest.mark.parametrize("name", sorted(DATE_PART_ALLOWED))
def test_changing_a_part_of_a_date_the_script_created_is_read_only(name):
    verdict = _classify(DATE_PART_ALLOWED[name])

    assert verdict.is_read_only is True, verdict.reason


@pytest.mark.parametrize("name", sorted(DATE_PART_DENIED))
def test_changing_a_part_of_anything_else_is_not_read_only(name):
    assert _classify(DATE_PART_DENIED[name]).is_read_only is False


ACCUMULATOR_ALLOWED = {
    "accumulator declared before the tell block": (
        'set out to ""\n'
        'tell application "Mail"\n'
        "  repeat with m in (messages of inbox)\n"
        "    set out to out & subject of m & linefeed\n"
        "  end repeat\n"
        "end tell\n"
        "return out"
    ),
    "camelCase accumulator first set inside the tell block": (
        'tell application "Mail"\n'
        '  set outText to ""\n'
        "  repeat with m in (messages of inbox)\n"
        "    set outText to outText & subject of m & linefeed\n"
        "  end repeat\n"
        "  return outText\n"
        "end tell"
    ),
}


@pytest.mark.parametrize("name", sorted(ACCUMULATOR_ALLOWED))
def test_the_accumulator_shapes_the_tool_description_recommends_are_read_only(name):
    verdict = _classify(ACCUMULATOR_ALLOWED[name])

    assert verdict.is_read_only is True, verdict.reason


def test_a_plain_word_accumulator_first_set_inside_a_tell_block_still_asks_for_approval():
    script = (
        'tell application "Mail"\n'
        '  set out to ""\n'
        "  repeat with m in (messages of inbox)\n"
        "    set out to out & subject of m & linefeed\n"
        "  end repeat\n"
        "  return out\n"
        "end tell"
    )

    verdict = _classify(script)

    assert verdict.is_read_only is False
    assert "application property" in verdict.reason


def test_the_recommendation_reaches_every_surface_a_script_writer_reads():
    from pathlib import Path

    import api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service as service_module
    from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import GenericAppleScriptService

    capabilities = GenericAppleScriptService().get_service_capabilities()
    slim_doc = capabilities["supported_methods"]["execute_applescript"]["slim_doc"]

    assert "declare accumulators before the 'tell' block" in slim_doc
    assert any("declare accumulator variables before the 'tell' block" in principle for principle in capabilities["execution_principles"])
    assert "16. In a read-only script, declare accumulator variables before the 'tell' block" in Path(service_module.__file__).read_text()


def test_the_activate_default_and_retry_wording_reaches_every_surface_a_script_writer_reads():
    from pathlib import Path

    import api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service as service_module
    from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import GenericAppleScriptService

    capabilities = GenericAppleScriptService().get_service_capabilities()
    slim_doc = capabilities["supported_methods"]["execute_applescript"]["slim_doc"]
    source = Path(service_module.__file__).read_text()

    assert "Leave 'activate' out of a read-only script on the first attempt" in slim_doc
    assert "only on a retry" in slim_doc
    assert any("leave 'activate' out on the first attempt" in principle for principle in capabilities["execution_principles"])
    assert "6. Include 'activate' only when the user asked to see or focus the application." in source
    assert "If the target application needs to be activated" not in source
