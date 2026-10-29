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
