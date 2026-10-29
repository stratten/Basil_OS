on run argv
	if (count of argv) is not 1 then
		error "Usage: osascript accessibility_smoke_test.applescript <validation-session-root>"
	end if

	set sessionRoot to item 1 of argv
	set tokenPath to quoted form of (sessionRoot & "/control-token")
	set token to do shell script "cat " & tokenPath
	set readyURL to "http://127.0.0.1:" & (do shell script "cat " & quoted form of (sessionRoot & "/backend.port")) & "/validation"
	set baseURL to text 1 thru ((offset of "/validation" in readyURL) - 1) of readyURL
	set screenshotsDir to sessionRoot & "/screenshots"
	set scriptDir to do shell script "dirname " & quoted form of (POSIX path of (path to me))
	set captureScript to quoted form of (scriptDir & "/capture_window.sh")
	do shell script "mkdir -p " & quoted form of screenshotsDir

	tell application "System Events"
		tell process "Basil Validation"
			set frontmost to true
			if not (exists menu item "Open HTML Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The static HTML validation control is unavailable."
			if not (exists menu item "Submit HTML Preview Feedback Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The HTML feedback validation control is unavailable."
			if not (exists menu item "Open Local Server Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The local-server validation control is unavailable."
			if not (exists menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The multi-run agent-task validation control is unavailable."
			if not (exists menu item "Open Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The managed history validation control is unavailable."
		end tell
	end tell

	set beforeHTMLRevision to do shell script "python3 -c " & quoted form of "import json, sys; print(json.load(open(sys.argv[1]))['htmlRevision'])" & " " & quoted form of (sessionRoot & "/fixtures/fixture-manifest.json")
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open HTML Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 50 times
				if exists window "report.html" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "report.html") then error "Validation HTML preview window did not open."
		end tell
	end tell
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "report.html" & " " & quoted form of (screenshotsDir & "/static-preview.png")

	set htmlMutation to do shell script "curl --fail --silent --show-error -X POST -H " & quoted form of ("X-Basil-Validation-Token: " & token) & " " & quoted form of (readyURL & "/fixtures/validation-html-live/mutate")
	set afterHTMLRevision to do shell script "python3 -c " & quoted form of "import json, sys; print(json.load(open(sys.argv[1]))['htmlRevision'])" & " " & quoted form of (sessionRoot & "/fixtures/fixture-manifest.json")

	if beforeHTMLRevision is afterHTMLRevision then
		error "Validation HTML revision did not change."
	end if
	if htmlMutation does not contain ("\"revision\":" & afterHTMLRevision) then
		error "Validation HTML mutation response did not report the new revision."
	end if

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Submit HTML Preview Feedback Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell

	set beforeLocalPreviewRevision to do shell script "python3 -c " & quoted form of "import json, sys; print(json.load(open(sys.argv[1]))['localPreviewRevision'])" & " " & quoted form of (sessionRoot & "/fixtures/fixture-manifest.json")
	set hasLocalPreviewSession to "python3 -c " & quoted form of "import json, pathlib, sys; path = pathlib.Path(sys.argv[1]); doc = json.loads(path.read_text()) if path.exists() else {}; entry = doc.get('validation-local-preview', {}); print('true' if entry.get('sessionID') else 'false')" & " " & quoted form of (sessionRoot & "/local-web-preview-evidence.json")
	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Local Server Preview Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 100 times
				if exists button "Approve" of window 1 then exit repeat
				if (do shell script hasLocalPreviewSession) is "true" then exit repeat
				delay 0.1
			end repeat
			if exists button "Approve" of window 1 then click button "Approve" of window 1
			set localPreviewWindowName to name of window 1
		end tell
	end tell
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of localPreviewWindowName & " " & quoted form of (screenshotsDir & "/local-server-preview.png")

	set localMutation to do shell script "curl --fail --silent --show-error -X POST -H " & quoted form of ("X-Basil-Validation-Token: " & token) & " " & quoted form of (readyURL & "/fixtures/validation-local-preview/mutate")
	set afterLocalPreviewRevision to do shell script "python3 -c " & quoted form of "import json, sys; print(json.load(open(sys.argv[1]))['localPreviewRevision'])" & " " & quoted form of (sessionRoot & "/fixtures/fixture-manifest.json")
	if beforeLocalPreviewRevision is afterLocalPreviewRevision then error "Local-preview revision did not change."
	if localMutation does not contain ("\"revision\":" & afterLocalPreviewRevision) then error "Local-preview mutation response did not report the new revision."

	set validationPython to "import asyncio
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid

session_root = pathlib.Path(os.environ['VALIDATION_SESSION_ROOT'])
base_url = os.environ['VALIDATION_BASE_URL']
report_path = session_root / 'full-local-preview-validation.json'
evidence_path = session_root / 'local-web-preview-evidence.json'

def request(path, method='GET', payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(base_url + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))

def poll_request(path):
    # A fast-lane discussion follow-up (see agent_task_submission_service.py's
    # handle_discussion_followup) answers over the WebSocket and persists its
    # AgentTask row asynchronously after the model call completes, so the
    # POST /process response returns before GET /agent-tasks/{id} is
    # queryable. A 404 here means \"not persisted yet\", not \"gone\" -- treat
    # it as a not-ready poll result rather than a fatal error.
    try:
        return request(path)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise

def wait_for(predicate, description, timeout_seconds=90):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise RuntimeError(f'Timed out waiting for {description}.')

def read_evidence(agent_task_id):
    if not evidence_path.exists():
        return None
    document = json.loads(evidence_path.read_text(encoding='utf-8'))
    return document.get(agent_task_id)

static_evidence = wait_for(
    lambda: item if (item := read_evidence('validation-html-live')) and item.get('screenshotPath') and 'BASIL_PREVIEW_RENDERED:' in item.get('consoleEvidence', '') else None,
    'static preview screenshot and console marker',
)
if not pathlib.Path(static_evidence['screenshotPath']).is_file() or pathlib.Path(static_evidence['screenshotPath']).stat().st_size == 0:
    raise RuntimeError('The static preview screenshot was not persisted.')

feedback_follow_up = wait_for(
    lambda: matching if (detail := request('/api/v1/agent-tasks/validation-html-live')) and (
        matching := next(
            (
                item for item in detail.get('follow_ups', [])
                if static_evidence['screenshotPath'] in item.get('reference_paths', [])
            ),
            None,
        )
    ) else None,
    'feedback follow-up screenshot reference',
    timeout_seconds=180,
)
feedback_task_id = feedback_follow_up.get('id')
if not isinstance(feedback_task_id, str) or not feedback_task_id:
    raise RuntimeError('The feedback follow-up did not expose an Agent Task identifier.')
feedback_task = wait_for(
    lambda: item if (item := poll_request(f'/api/v1/agent-tasks/{feedback_task_id}')) and item.get('status') in {'completed', 'failed', 'cancelled'} else None,
    'feedback follow-up completion',
    timeout_seconds=180,
)
if feedback_task.get('status') != 'completed':
    raise RuntimeError('The feedback follow-up did not complete successfully.')

local_evidence = wait_for(
    lambda: item if (item := read_evidence('validation-local-preview')) and item.get('sessionID') and ('BASIL_PREVIEW_RENDERED:' + os.environ['LOCAL_PREVIEW_REVISION']) in item.get('consoleEvidence', '') else None,
    'local preview server evidence',
)
session_id = local_evidence['sessionID']
session = wait_for(
    lambda: item if (item := poll_request(f'/api/v1/agent-tasks/validation-local-preview/artifacts/validation-index/local-preview/sessions/{session_id}')) and item.get('status') == 'running' and item.get('url') == 'http://127.0.0.1:43123' else None,
    'approved loopback server',
)

models_payload = request('/settings/api_models/reasoning')
models = models_payload.get('models', [])
local_model = next((model for model in models if model.get('category') == 'local'), None)
api_model = next((model for model in models if model.get('category') in {'api', 'custom'}), None)
if local_model is None or api_model is None:
    raise RuntimeError('An installed local and an enabled API/custom reasoning model are both required.')

def run_model_validation(model):
    task_id = str(uuid.uuid4())
    request(
        '/api/v1/agent-tasks/process',
        method='POST',
        payload={
            'agent_task': 'Reply with exactly BASIL_PREVIEW_VALIDATION_OK. Do not use tools, applications, browser, files, or network.',
            'agent_task_id': task_id,
            'root_task_id': 'validation-html-live',
            'previous_task_id': 'validation-html-live',
            'model_id': model['id'],
        },
    )
    detail = wait_for(
        lambda: item if (item := poll_request(f'/api/v1/agent-tasks/{task_id}')) and item.get('status') in {'completed', 'failed', 'cancelled'} else None,
        'terminal result for {}'.format(model['id']),
        timeout_seconds=180,
    )
    timeline = detail.get('execution_timeline') or []
    if detail.get('status') != 'completed' or 'BASIL_PREVIEW_VALIDATION_OK' not in (detail.get('result_message') or ''):
        raise RuntimeError('Model validation failed for {}.'.format(model['id']))
    if any(str(entry.get('type', '')).lower() in {'tool', 'approval', 'browser'} for entry in timeline if isinstance(entry, dict)):
        raise RuntimeError('Model validation used a disallowed tool path for {}.'.format(model['id']))
    return {'modelID': model['id'], 'category': model['category'], 'agentTaskID': task_id}

model_runs = [run_model_validation(local_model), run_model_validation(api_model)]
report = {
    'staticEvidence': static_evidence,
    'localServerSession': session,
    'localPreviewRevision': int(os.environ['LOCAL_PREVIEW_REVISION']),
    'modelRuns': model_runs,
    'status': 'passed',
}
report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(report_path)
"
	set validationCommand to "VALIDATION_SESSION_ROOT=" & quoted form of sessionRoot & " VALIDATION_BASE_URL=" & quoted form of baseURL & " LOCAL_PREVIEW_REVISION=" & quoted form of afterLocalPreviewRevision & " python3 -c " & quoted form of validationPython
	do shell script validationCommand

	set managedHistoryPath to sessionRoot & "/fixtures/documents/managed-history-fixture.txt"
	set managedHistoryPrePython to "import json
import os
import pathlib
import urllib.parse
import urllib.request

base_url = os.environ['VALIDATION_BASE_URL']
token = os.environ['VALIDATION_TOKEN']
fixture_path = pathlib.Path(os.environ['MANAGED_HISTORY_PATH'])

def post_mutate():
    req = urllib.request.Request(
        base_url + '/validation/fixtures/validation-managed-history/mutate',
        method='POST',
        headers={'X-Basil-Validation-Token': token},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))

def get_versions():
    encoded_path = urllib.parse.quote(str(fixture_path), safe='')
    req = urllib.request.Request(
        base_url + '/api/v1/agent-tasks/managed-file-history/versions?canonical_path=' + encoded_path,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))

post_mutate()
post_mutate()
versions = get_versions()['versions']
if len(versions) != 2:
    raise RuntimeError(f'Expected 2 managed history versions before restore, found {len(versions)}.')
if fixture_path.read_text(encoding='utf-8') != 'Managed history fixture v3\\n':
    raise RuntimeError('Managed history fixture did not reach v3 before the restore step.')
print('managed-history-pre-restore-ok')
"
	set managedHistoryPreCommand to "VALIDATION_BASE_URL=" & quoted form of baseURL & " VALIDATION_TOKEN=" & quoted form of token & " MANAGED_HISTORY_PATH=" & quoted form of managedHistoryPath & " python3 -c " & quoted form of managedHistoryPrePython
	do shell script managedHistoryPreCommand

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 50 times
				if exists window "AgentTask History" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask History") then error "The managed history fixture window did not open."
			if exists button "Preview managed-history-fixture.txt" of window "AgentTask History" then
				click button "Preview managed-history-fixture.txt" of window "AgentTask History"
			end if
		end tell
	end tell
	delay 1
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask History" & " " & quoted form of (screenshotsDir & "/managed-history-before-restore.png")

	tell application "System Events"
		tell process "Basil Validation"
			if not (exists button "Restore" of window "AgentTask History") then error "The managed history restore control did not appear."
			click button "Restore" of window "AgentTask History"
		end tell
	end tell
	delay 1
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask History" & " " & quoted form of (screenshotsDir & "/managed-history-after-restore.png")

	set managedHistoryPostPython to "import os
import pathlib

fixture_path = pathlib.Path(os.environ['MANAGED_HISTORY_PATH'])
content = fixture_path.read_text(encoding='utf-8')
if content != 'Managed history fixture v2\\n':
    raise RuntimeError(f'Managed history fixture was not restored to v2; found: {content!r}')
print('managed-history-restore-ok')
"
	set managedHistoryPostCommand to "MANAGED_HISTORY_PATH=" & quoted form of managedHistoryPath & " python3 -c " & quoted form of managedHistoryPostPython
	do shell script managedHistoryPostCommand

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 50 times
				if exists window "AgentTask" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask") then error "The multi-run agent-task fixture window did not open."
		end tell
	end tell
	delay 1
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask" & " " & quoted form of (screenshotsDir & "/run-history.png")

	tell application "System Events"
		tell process "Basil Validation"
			click button "Task history · 3 runs" of window "AgentTask"
			set rootRow to first button of window "AgentTask" whose name contains "Initial request:"
			click rootRow
		end tell
	end tell
	delay 0.5
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask" & " " & quoted form of (screenshotsDir & "/run-history-root-focused.png")

	tell application "System Events"
		tell process "Basil Validation"
			set middleRow to first button of window "AgentTask" whose name contains "Follow-up 1:"
			click middleRow
		end tell
	end tell
	delay 0.5
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask" & " " & quoted form of (screenshotsDir & "/run-history-middle-focused.png")

	tell application "System Events"
		tell process "Basil Validation"
			set newestRow to first button of window "AgentTask" whose name contains "Follow-up 2:"
			click newestRow
		end tell
	end tell

	tell application "System Events"
		tell process "Basil Validation"
			if not (exists menu item "Close Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The close multi-run fixture validation control is unavailable."
			click menu item "Close Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 50 times
				if not (exists window "AgentTask") then exit repeat
				delay 0.1
			end repeat
			if exists window "AgentTask" then error "The multi-run agent-task fixture window did not close."
		end tell
	end tell

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Multi-Run Agent-Task Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 50 times
				if exists window "AgentTask" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask") then error "The multi-run agent-task fixture window did not reopen."
			if not (exists button "Task history · 3 runs" of window "AgentTask") then error "Reopening the fixture did not restore the multi-run history tray."
		end tell
	end tell
	do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "AgentTask" & " " & quoted form of (screenshotsDir & "/run-history-reopened.png")

	tell application "System Events"
		tell process "Basil Validation"
			if exists menu item "Close Local Preview Window" of menu "Validation" of menu bar item "Validation" of menu bar 1 then
				click menu item "Close Local Preview Window" of menu "Validation" of menu bar item "Validation" of menu bar 1
			else
				error "The Close Local Preview Window validation menu item is unavailable."
			end if
		end tell
	end tell
	set shutdownPython to "import json
import socket
import sys
import time
import urllib.request

base_url, session_root = sys.argv[1:]
evidence_document = json.load(open(session_root + '/local-web-preview-evidence.json', encoding='utf-8'))
session_id = evidence_document['validation-local-preview']['sessionID']
url = base_url + '/api/v1/agent-tasks/validation-local-preview/artifacts/validation-index/local-preview/sessions/' + session_id
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    with urllib.request.urlopen(url, timeout=5) as response:
        session = json.loads(response.read().decode('utf-8'))
    if session.get('status') == 'stopped':
        break
    time.sleep(0.25)
else:
    raise RuntimeError('The local preview session did not stop after closing the preview.')
socket_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    if socket_probe.connect_ex(('127.0.0.1', 43123)) == 0:
        raise RuntimeError('The local preview port is still listening after close.')
finally:
    socket_probe.close()
"
	do shell script "python3 -c " & quoted form of shutdownPython & " " & quoted form of baseURL & " " & quoted form of sessionRoot
end run
