on run argv
	if (count of argv) is not 1 then
		error "Usage: osascript local_preview_server_acceptance.applescript <validation-session-root>"
	end if

	set sessionRoot to item 1 of argv
	set backendPort to do shell script "cat " & quoted form of (sessionRoot & "/backend.port")
	set baseURL to "http://127.0.0.1:" & backendPort
	set evidencePath to sessionRoot & "/local-web-preview-evidence.json"
	set screenshotsDir to sessionRoot & "/screenshots"
	set scriptDir to do shell script "dirname " & quoted form of (POSIX path of (path to me))
	set captureScript to quoted form of (scriptDir & "/capture_window.sh")
	do shell script "mkdir -p " & quoted form of screenshotsDir

	tell application "System Events"
		tell process "Basil Validation"
			set frontmost to true
			if not (exists menu item "Open Local Server Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The local-server open validation control is unavailable."
			if not (exists menu item "Open Local Server Preview Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The local-server task-fixture validation control is unavailable."
			if not (exists menu item "Submit Local Server Preview Feedback Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The local-server feedback validation control is unavailable."
			if not (exists menu item "Close Local Preview Window" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The close-preview-window validation control is unavailable."
			if not (exists menu item "Close Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The shared-widget close validation control is unavailable."
		end tell
	end tell

	-- Keep the AgentTask History window open on this fixture's task for the
	-- whole run so every execution_approval_request broadcast for it has a
	-- real ApprovalOverlay to render into.
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Local Server Preview Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if exists window "AgentTask History" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask History") then error "The AgentTask History window did not open for the local-server fixture task."
		end tell
	end tell

	-- Step 4: deny the first server-start request. Assert denied status, no
	-- process, no PID, and no feedback-success state.
	my deleteEvidenceEntry(evidencePath, "validation-local-preview")
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Local Server Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell
	my waitAndClickButton("AgentTask History", "Deny", 600)
	set deniedSessionId to my assertDeniedSession(evidencePath, baseURL)
	my captureWindow(captureScript, "index.html", screenshotsDir & "/local-server-denied.png")
	my closePreviewWindow()

	-- Step 5 (re-verified): approve the second request. Assert exact
	-- command/cwd/host/port/loopback-URL and a running status.
	my openAndApproveServerPreview()
	set firstRunningSessionId to my assertRunningSession(baseURL, "", evidencePath)
	my captureWindow(captureScript, "index.html", screenshotsDir & "/local-server-approved-running.png")

	-- Step 6: submit feedback against the running server-preview fixture.
	-- Assert the created follow-up retains provenance via the same
	-- reference_paths/screenshot mechanism already proven for the static
	-- fixture, and reaches a terminal status.
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Submit Local Server Preview Feedback Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell
	my assertFeedbackFollowUp(evidencePath, baseURL)

	-- Step 7 (re-verified): stop explicitly. Assert stopped state and that
	-- the loopback port is no longer accepting connections.
	my closePreviewWindow()
	my assertStoppedSessionAndPortClosed(baseURL, firstRunningSessionId)

	-- Step 8: start a second approved session against the same fixture
	-- identity and close it via native window close. Assert it replaced the
	-- first (different session ID, first stays durably stopped) and reaps
	-- the same way.
	my openAndApproveServerPreview()
	set secondRunningSessionId to my assertRunningSession(baseURL, firstRunningSessionId, evidencePath)
	if secondRunningSessionId is firstRunningSessionId then error "The second session reused the first session's identity instead of replacing it."
	my closePreviewWindow()
	my assertStoppedSessionAndPortClosed(baseURL, secondRunningSessionId)
	my assertStoppedSessionAndPortClosed(baseURL, firstRunningSessionId)

	-- Step 9: reopen after the stopped session. Assert a fresh session
	-- starts independently (not the stale one) and reaches running.
	my openAndApproveServerPreview()
	set reopenedSessionId to my assertRunningSession(baseURL, secondRunningSessionId, evidencePath)
	if reopenedSessionId is secondRunningSessionId then error "Reopening after stop reused the previous stopped session instead of starting a fresh one."
	my captureWindow(captureScript, "index.html", screenshotsDir & "/local-server-reopened-running.png")
	my closePreviewWindow()
	my assertStoppedSessionAndPortClosed(baseURL, reopenedSessionId)
	my captureWindow(captureScript, "", screenshotsDir & "/local-server-stopped.png")

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Close Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell
end run

on openAndApproveServerPreview()
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Local Server Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if exists window "index.html" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "index.html") then error "The local-server preview window did not open."
		end tell
	end tell
	my waitAndClickButton("AgentTask History", "Approve", 600)
end openAndApproveServerPreview

on findButtonRef(windowName, buttonName)
	tell application "System Events"
		tell process "Basil Validation"
			set allElements to entire contents of window windowName
			repeat with elem in allElements
				try
					if (class of elem is button) and (name of elem as string) is buttonName then
						return elem
					end if
				end try
			end repeat
		end tell
	end tell
	return missing value
end findButtonRef

on waitAndClickButton(windowName, buttonName, timeoutIterations)
	repeat timeoutIterations times
		set btn to my findButtonRef(windowName, buttonName)
		if btn is not missing value then
			tell application "System Events"
				tell process "Basil Validation"
					click btn
				end tell
			end tell
			return
		end if
		delay 0.1
	end repeat
	error "The " & buttonName & " control did not appear in window " & windowName & "."
end waitAndClickButton

on closePreviewWindow()
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Close Local Preview Window" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if not (exists window "index.html") then exit repeat
				delay 0.1
			end repeat
			if exists window "index.html" then error "The local-server preview window did not close."
		end tell
	end tell
end closePreviewWindow

on captureWindow(captureScript, titleSubstring, outputPath)
	do shell script "rm -f " & quoted form of outputPath
	repeat 10 times
		try
			do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of titleSubstring & " " & quoted form of outputPath
			if (do shell script "test -s " & quoted form of outputPath & " && echo ok || echo missing") is "ok" then
				return
			end if
		end try
		delay 0.2
	end repeat
	error "Failed to capture a non-empty screenshot at " & outputPath
end captureWindow

on deleteEvidenceEntry(evidencePath, agentTaskId)
	set deletePython to "
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists():
    sys.exit(0)
document = json.loads(path.read_text())
document.pop(sys.argv[2], None)
path.write_text(json.dumps(document))
"
	do shell script "python3 -c " & quoted form of deletePython & " " & quoted form of evidencePath & " " & quoted form of agentTaskId
end deleteEvidenceEntry

on assertDeniedSession(evidencePath, baseURL)
	set deniedPython to "
import json, pathlib, sys, time, urllib.error, urllib.request

evidence_path, base_url = sys.argv[1], sys.argv[2]

def read_evidence():
    path = pathlib.Path(evidence_path)
    if not path.exists():
        return None
    document = json.loads(path.read_text())
    return document.get('validation-local-preview')

def poll_session(session_id):
    url = f'{base_url}/api/v1/agent-tasks/validation-local-preview/artifacts/validation-index/local-preview/sessions/{session_id}'
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise

deadline = time.monotonic() + 30
entry = None
while time.monotonic() < deadline:
    entry = read_evidence()
    if entry and entry.get('sessionID') and entry.get('deniedReason'):
        break
    time.sleep(0.25)
if not entry or not entry.get('sessionID') or not entry.get('deniedReason'):
    raise SystemExit('Timed out waiting for denied-session evidence.')

session_id = entry['sessionID']
deadline = time.monotonic() + 30
session = None
while time.monotonic() < deadline:
    session = poll_session(session_id)
    if session and session.get('status') == 'denied':
        break
    time.sleep(0.25)
if not session or session.get('status') != 'denied':
    raise SystemExit('Timed out waiting for the backend to report the session as denied.')
if session.get('pid') is not None:
    raise SystemExit('A denied session must not have a registered process ID.')
if not session.get('last_error'):
    raise SystemExit('A denied session must record a denial reason.')
print(session_id)
"
	return do shell script "python3 -c " & quoted form of deniedPython & " " & quoted form of evidencePath & " " & quoted form of baseURL
end assertDeniedSession

on assertRunningSession(baseURL, previousSessionId, evidencePath)
	set runningPython to "
import json, sys, time, urllib.request

base_url, previous_session_id, evidence_path = sys.argv[1], sys.argv[2], sys.argv[3]

def poll_session(session_id):
    url = f'{base_url}/api/v1/agent-tasks/validation-local-preview/artifacts/validation-index/local-preview/sessions/{session_id}'
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))

def read_evidence():
    with open(evidence_path) as handle:
        document = json.load(handle)
    return document.get('validation-local-preview')

deadline = time.monotonic() + 30
session_id = None
while time.monotonic() < deadline:
    entry = read_evidence()
    if entry and entry.get('sessionID') and entry['sessionID'] != previous_session_id:
        session_id = entry['sessionID']
        break
    time.sleep(0.25)
if not session_id:
    raise SystemExit('Timed out waiting for a new session ID to appear in evidence.')

deadline = time.monotonic() + 30
session = None
while time.monotonic() < deadline:
    session = poll_session(session_id)
    if session and session.get('status') == 'running':
        break
    time.sleep(0.25)
if not session or session.get('status') != 'running':
    raise SystemExit('Timed out waiting for the approved session to report running.')
if session.get('url') != 'http://127.0.0.1:43123':
    raise SystemExit(f\"Unexpected loopback URL: {session.get('url')}\")
if session.get('command') != 'python3':
    raise SystemExit(f\"Unexpected command: {session.get('command')}\")
if session.get('args') != ['server.py', '--host', '127.0.0.1', '--port', '43123']:
    raise SystemExit(f\"Unexpected args: {session.get('args')}\")
if not session.get('cwd', '').endswith('local-preview'):
    raise SystemExit(f\"Unexpected cwd: {session.get('cwd')}\")
if session.get('host') != '127.0.0.1' or session.get('port') != 43123:
    raise SystemExit(f\"Unexpected host/port: {session.get('host')}:{session.get('port')}\")
if session.get('pid') is None:
    raise SystemExit('A running session must have a registered process ID.')
print(session_id)
"
	return do shell script "python3 -c " & quoted form of runningPython & " " & quoted form of baseURL & " " & quoted form of previousSessionId & " " & quoted form of evidencePath
end assertRunningSession

on assertFeedbackFollowUp(evidencePath, baseURL)
	-- The feedback follow-up is a fresh agent task whose own diagnostic
	-- shell commands (issued by the model while it inspects the running
	-- server-preview) are not all classified read-only by the backend's
	-- risk assessment -- compound commands mixing lsof/curl with shell
	-- operators such as `||` fall through to a live execution_approval_request
	-- even with auto_approve_read_only enabled. Since this is the model's
	-- own incidental diagnostic tooling rather than anything the runner
	-- controls, this loop must keep auto-approving any such prompt that
	-- appears on "AgentTask History" while it waits for the follow-up to
	-- reach a terminal status, exactly as it already does for the
	-- deliberate server-start approval steps above.
	set screenshotPath to my waitForFeedbackScreenshot(evidencePath)
	set followUpId to ""
	set finalStatus to ""
	repeat 720 times
		set approveButton to my findButtonRef("AgentTask History", "Approve")
		if approveButton is not missing value then
			tell application "System Events"
				tell process "Basil Validation"
					click approveButton
				end tell
			end tell
		end if
		set checkResult to my checkFeedbackFollowUp(baseURL, screenshotPath, followUpId)
		set resultParts to my splitOnColon(checkResult)
		set resultKind to item 1 of resultParts
		if resultKind is "FOLLOWUP" then
			set followUpId to item 2 of resultParts
		else if resultKind is "STATUS" then
			set followUpId to item 2 of resultParts
			set finalStatus to item 3 of resultParts
			if finalStatus is "completed" then
				return followUpId
			else if finalStatus is "failed" or finalStatus is "cancelled" then
				error "The server-preview feedback follow-up did not complete successfully."
			end if
		end if
		delay 0.5
	end repeat
	error "Timed out waiting for the server-preview feedback follow-up to reach a terminal status."
end assertFeedbackFollowUp

on waitForFeedbackScreenshot(evidencePath)
	set screenshotPython to "
import json, pathlib, sys, time

evidence_path = sys.argv[1]

def read_evidence():
    path = pathlib.Path(evidence_path)
    if not path.exists():
        return None
    document = json.loads(path.read_text())
    return document.get('validation-local-preview')

deadline = time.monotonic() + 30
screenshot_path = None
while time.monotonic() < deadline:
    entry = read_evidence()
    if entry and entry.get('screenshotPath'):
        screenshot_path = entry['screenshotPath']
        break
    time.sleep(0.25)
if not screenshot_path:
    raise SystemExit('Timed out waiting for a server-preview feedback screenshot to be persisted.')
print(screenshot_path)
"
	return do shell script "python3 -c " & quoted form of screenshotPython & " " & quoted form of evidencePath
end waitForFeedbackScreenshot

on checkFeedbackFollowUp(baseURL, screenshotPath, knownFollowUpId)
	-- Single-shot status probe (no internal sleep loop) so the caller can
	-- interleave Approve-button polling between calls.
	set checkPython to "
import json, sys, urllib.error, urllib.request

base_url, screenshot_path, known_follow_up_id = sys.argv[1], sys.argv[2], sys.argv[3]

def poll_request(path):
    req = urllib.request.Request(base_url + path)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise

if known_follow_up_id:
    task = poll_request(f'/api/v1/agent-tasks/{known_follow_up_id}')
    status = task.get('status') if task else 'unknown'
    print(f'STATUS:{known_follow_up_id}:{status}')
    sys.exit(0)

detail = poll_request('/api/v1/agent-tasks/validation-local-preview')
follow_up = None
if detail:
    follow_up = next(
        (item for item in detail.get('follow_ups', []) if screenshot_path in item.get('reference_paths', [])),
        None,
    )
if not follow_up:
    print('PENDING:none')
    sys.exit(0)
follow_up_id = follow_up.get('id')
if not isinstance(follow_up_id, str) or not follow_up_id:
    print('PENDING:none')
    sys.exit(0)
print(f'FOLLOWUP:{follow_up_id}')
"
	return do shell script "python3 -c " & quoted form of checkPython & " " & quoted form of baseURL & " " & quoted form of screenshotPath & " " & quoted form of knownFollowUpId
end checkFeedbackFollowUp

on splitOnColon(theText)
	set previousDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to ":"
	set theParts to text items of theText
	set AppleScript's text item delimiters to previousDelimiters
	return theParts
end splitOnColon

on assertStoppedSessionAndPortClosed(baseURL, sessionId)
	set stoppedPython to "
import json, socket, sys, time, urllib.request

base_url, session_id = sys.argv[1], sys.argv[2]

def poll_session():
    url = f'{base_url}/api/v1/agent-tasks/validation-local-preview/artifacts/validation-index/local-preview/sessions/{session_id}'
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))

deadline = time.monotonic() + 30
session = None
while time.monotonic() < deadline:
    session = poll_session()
    if session and session.get('status') == 'stopped':
        break
    time.sleep(0.25)
if not session or session.get('status') != 'stopped':
    raise SystemExit(f'Timed out waiting for session {session_id} to report stopped.')

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.settimeout(2)
    result = probe.connect_ex(('127.0.0.1', 43123))
if result == 0:
    raise SystemExit('The loopback preview port is still accepting connections after stop.')
"
	do shell script "python3 -c " & quoted form of stoppedPython & " " & quoted form of baseURL & " " & quoted form of sessionId
end assertStoppedSessionAndPortClosed
