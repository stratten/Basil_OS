on run argv
	if (count of argv) is not 1 then
		error "Usage: osascript run_history_acceptance.applescript <validation-session-root>"
	end if

	set sessionRoot to item 1 of argv
	set statePath to sessionRoot & "/run-history-focus-state.json"
	set screenshotsDir to sessionRoot & "/screenshots"
	set scriptDir to do shell script "dirname " & quoted form of (POSIX path of (path to me))
	set captureScript to quoted form of (scriptDir & "/capture_window.sh")
	do shell script "mkdir -p " & quoted form of screenshotsDir

	tell application "System Events"
		tell process "Basil Validation"
			set frontmost to true
			if not (exists menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The multi-run fixture validation control is unavailable."
			if not (exists menu item "Close Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The close multi-run fixture validation control is unavailable."
			if not (exists menu item "Assert Multi-Run Initial Focus" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The initial-focus validation control is unavailable."
			if not (exists menu item "Focus Multi-Run Root" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The root-focus validation control is unavailable."
			if not (exists menu item "Focus Multi-Run Middle" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The middle-focus validation control is unavailable."
			if not (exists menu item "Focus Multi-Run Newest" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The newest-focus validation control is unavailable."
			click menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell

	tell application "System Events"
		tell process "Basil Validation"
			repeat 600 times
				if exists window "AgentTask" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask") then error "The multi-run Agent Task fixture did not open."
		end tell
	end tell

	my assertInitialFocusWithRetry(statePath, 60)
	my captureWindow(captureScript, screenshotsDir & "/run-history-newest-initial.png")

	my assertFocusedRun(statePath, "Focus Multi-Run Root", "validation-run-history-root", "Inspect the integration workflow and prepare its baseline evidence.", "Run 1 is ready for history review.", "/fixtures/documents/run-summary.md", "validation-run-summary")
	my captureWindow(captureScript, screenshotsDir & "/run-history-root-focused.png")

	my assertFocusedRun(statePath, "Focus Multi-Run Middle", "validation-run-history-follow-up-1", "Add the deployment constraints found during the review.", "Run 2 is ready for history review.", "/fixtures/documents/notes.txt", "validation-notes")
	my captureWindow(captureScript, screenshotsDir & "/run-history-middle-focused.png")

	my assertFocusedRun(statePath, "Focus Multi-Run Newest", "validation-run-history-follow-up-2", "Produce the final implementation brief with the reviewed evidence.", "Run 3 is ready for history review.", "/fixtures/documents/preview.py", "validation-preview")
	my captureWindow(captureScript, screenshotsDir & "/run-history-newest-focused.png")

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Close Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if not (exists window "AgentTask") then exit repeat
				delay 0.1
			end repeat
			if exists window "AgentTask" then error "The multi-run Agent Task fixture did not close."
			click menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if exists window "AgentTask" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask") then error "The multi-run Agent Task fixture did not reopen."
		end tell
	end tell

	my assertInitialFocusWithRetry(statePath, 60)
	my captureWindow(captureScript, screenshotsDir & "/run-history-reopened.png")
end run

on assertInitialFocusWithRetry(statePath, timeoutSeconds)
	set attempts to timeoutSeconds div 3
	set lastError to "no acknowledgement was written"
	repeat with attempt from 1 to attempts
		my deleteState(statePath)
		tell application "System Events"
			tell process "Basil Validation"
				click menu item "Assert Multi-Run Initial Focus" of menu "Validation" of menu bar item "Validation" of menu bar 1
			end tell
		end tell
		try
			my assertFocusState(statePath, "validation-run-history-follow-up-2", "Produce the final implementation brief with the reviewed evidence.", "Run 3 is ready for history review.", "/fixtures/documents/preview.py", "validation-preview", 3)
			return
		on error errorMessage
			set lastError to errorMessage
		end try
	end repeat
	error "The initial newest-run focus acknowledgement did not arrive: " & lastError
end assertInitialFocusWithRetry

on assertFocusedRun(statePath, menuTitle, expectedRunId, expectedRequestText, expectedResultText, expectedDocumentSuffix, expectedArtifactId)
	my deleteState(statePath)
	tell application "System Events"
		tell process "Basil Validation"
			click menu item menuTitle of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell
	my assertFocusState(statePath, expectedRunId, expectedRequestText, expectedResultText, expectedDocumentSuffix, expectedArtifactId, 60)
end assertFocusedRun

on deleteState(statePath)
	do shell script "rm -f " & quoted form of statePath
end deleteState

on assertFocusState(statePath, expectedRunId, expectedRequestText, expectedResultText, expectedDocumentSuffix, expectedArtifactId, timeoutSeconds)
	set validationPython to "import json
import pathlib
import sys
import time

state_path = pathlib.Path(sys.argv[1])
expected_run_id, expected_request_text, expected_result_text, expected_document_suffix, expected_artifact_id = sys.argv[2:7]
deadline = time.monotonic() + float(sys.argv[7])
last_error = 'state file was not written'
while time.monotonic() < deadline:
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
            assert state.get('schemaVersion') == 1
            assert isinstance(state.get('requestId'), str) and state['requestId']
            assert state.get('rootTaskId') == 'validation-run-history-root'
            assert state.get('runId') == expected_run_id
            assert state.get('requestText') == expected_request_text
            assert state.get('resultText') == expected_result_text
            assert any(isinstance(path, str) and path.endswith(expected_document_suffix) for path in state.get('documentPaths', []))
            assert expected_artifact_id in state.get('artifactIds', [])
            assert state.get('isOverviewOpen') is True
            assert isinstance(state.get('observedAt'), str) and state['observedAt']
            sys.exit(0)
        except (AssertionError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            last_error = str(error) or error.__class__.__name__
    time.sleep(0.1)
raise SystemExit(f'Timed out waiting for matching run-focus state: {last_error}')
"
	do shell script "python3 -c " & quoted form of validationPython & " " & quoted form of statePath & " " & quoted form of expectedRunId & " " & quoted form of expectedRequestText & " " & quoted form of expectedResultText & " " & quoted form of expectedDocumentSuffix & " " & quoted form of expectedArtifactId & " " & timeoutSeconds
end assertFocusState

on captureWindow(captureScript, outputPath)
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask" & " " & quoted form of outputPath
	do shell script "test -s " & quoted form of outputPath
end captureWindow
