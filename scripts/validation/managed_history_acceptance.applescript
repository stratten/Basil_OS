on run argv
	if (count of argv) is not 1 then
		error "Usage: osascript managed_history_acceptance.applescript <validation-session-root>"
	end if

	set sessionRoot to item 1 of argv
	set token to do shell script "cat " & quoted form of (sessionRoot & "/control-token")
	set backendPort to do shell script "cat " & quoted form of (sessionRoot & "/backend.port")
	set baseURL to "http://127.0.0.1:" & backendPort
	set managedHistoryPath to sessionRoot & "/fixtures/documents/managed-history-fixture.txt"
	set statePath to sessionRoot & "/managed-history-acceptance-state.json"
	set screenshotsDir to sessionRoot & "/screenshots"
	set scriptDir to do shell script "dirname " & quoted form of (POSIX path of (path to me))
	set captureScript to quoted form of (scriptDir & "/capture_window.sh")
	do shell script "mkdir -p " & quoted form of screenshotsDir

	tell application "System Events"
		tell process "Basil Validation"
			set frontmost to true
			if not (exists menu item "Open Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The managed-history open validation control is unavailable."
			if not (exists menu item "Close Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The managed-history close validation control is unavailable."
			if not (exists menu item "Restore Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1) then error "The managed-history restore validation control is unavailable."
		end tell
	end tell

	my prepareManagedHistoryFixture(baseURL, token, managedHistoryPath, statePath)

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Open Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if exists window "AgentTask History" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask History") then error "The managed-history fixture window did not open."
		end tell
	end tell

	my captureWindow(captureScript, screenshotsDir & "/managed-history-before-restore.png")

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Restore Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
		end tell
	end tell
	my assertRestoredManagedHistory(baseURL, managedHistoryPath, statePath)
	my captureWindow(captureScript, screenshotsDir & "/managed-history-after-restore.png")

	tell application "System Events"
		tell process "Basil Validation"
			click menu item "Close Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if not (exists window "AgentTask History") then exit repeat
				delay 0.1
			end repeat
			if exists window "AgentTask History" then error "The managed-history fixture window did not close."
			click menu item "Open Managed History Fixture" of menu "Validation" of menu bar item "Validation" of menu bar 1
			repeat 600 times
				if exists window "AgentTask History" then exit repeat
				delay 0.1
			end repeat
			if not (exists window "AgentTask History") then error "The managed-history fixture window did not reopen."
		end tell
	end tell

	my assertRestoredManagedHistory(baseURL, managedHistoryPath, statePath)
	my captureWindow(captureScript, screenshotsDir & "/managed-history-reopened.png")
end run

on prepareManagedHistoryFixture(baseURL, token, managedHistoryPath, statePath)
	set validationPython to "import json
import pathlib
import sys
import urllib.parse
import urllib.request

base_url, token, fixture_path_value, state_path_value = sys.argv[1:]
fixture_path = pathlib.Path(fixture_path_value)
state_path = pathlib.Path(state_path_value)

def request(path, method='GET'):
    request = urllib.request.Request(
        base_url + path,
        method=method,
        headers={'X-Basil-Validation-Token': token},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))

for _ in range(2):
    request('/validation/fixtures/validation-managed-history/mutate', method='POST')

encoded_path = urllib.parse.quote(str(fixture_path), safe='')
versions = request('/api/v1/agent-tasks/managed-file-history/versions?canonical_path=' + encoded_path)['versions']
if len(versions) != 2:
    raise RuntimeError(f'Expected two versions before restore, found {len(versions)}.')
expected_contents = ['Managed history fixture v3\\n', 'Managed history fixture v2\\n']
for index, version in enumerate(versions):
    if version.get('root_task_id') != 'validation-managed-history' or version.get('agent_task_id') != 'validation-managed-history':
        raise RuntimeError(f'Unexpected managed-history provenance: {version!r}')
    if version.get('origin') != 'model' or version.get('restores_change_id') is not None:
        raise RuntimeError(f'Unexpected pre-restore version state: {version!r}')
    content = request('/api/v1/agent-tasks/managed-file-history/versions/' + urllib.parse.quote(version['id'], safe='') + '/content')
    if content.get('content') != expected_contents[index]:
        raise RuntimeError(f'Unexpected pre-restore content at index {index}: {content!r}')
if fixture_path.read_text(encoding='utf-8') != expected_contents[0]:
    raise RuntimeError('The managed-history fixture did not reach v3 before restore.')
state_path.write_text(json.dumps({
    'canonicalPath': str(fixture_path),
    'restoreTargetChangeId': versions[1]['id'],
}, sort_keys=True), encoding='utf-8')
"
	do shell script "python3 -c " & quoted form of validationPython & " " & quoted form of baseURL & " " & quoted form of token & " " & quoted form of managedHistoryPath & " " & quoted form of statePath
end prepareManagedHistoryFixture

on assertRestoredManagedHistory(baseURL, managedHistoryPath, statePath)
	set validationPython to "import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

base_url, fixture_path_value, state_path_value = sys.argv[1:]
fixture_path = pathlib.Path(fixture_path_value)
state = json.loads(pathlib.Path(state_path_value).read_text(encoding='utf-8'))
deadline = time.monotonic() + 60
last_error = 'restore did not reach durable state'
while time.monotonic() < deadline:
    try:
        encoded_path = urllib.parse.quote(str(fixture_path), safe='')
        request = urllib.request.Request(base_url + '/api/v1/agent-tasks/managed-file-history/versions?canonical_path=' + encoded_path)
        with urllib.request.urlopen(request, timeout=20) as response:
            versions = json.loads(response.read().decode('utf-8'))['versions']
        if fixture_path.read_text(encoding='utf-8') != 'Managed history fixture v2\\n':
            raise RuntimeError('fixture content is not v2')
        if len(versions) != 3:
            raise RuntimeError(f'expected three versions, found {len(versions)}')
        head = versions[0]
        if head.get('operation') != 'rollback' or head.get('origin') != 'user':
            raise RuntimeError(f'unexpected rollback head: {head!r}')
        if head.get('root_task_id') != 'validation-managed-history' or head.get('agent_task_id') != 'validation-managed-history':
            raise RuntimeError(f'unexpected rollback provenance: {head!r}')
        if head.get('restores_change_id') != state['restoreTargetChangeId']:
            raise RuntimeError(f'unexpected restore target: {head!r}')
        raise SystemExit(0)
    except (OSError, ValueError, KeyError, RuntimeError, urllib.error.URLError) as error:
        last_error = str(error)
        time.sleep(0.1)
raise SystemExit(f'Timed out waiting for durable managed-history restore: {last_error}')
"
	do shell script "python3 -c " & quoted form of validationPython & " " & quoted form of baseURL & " " & quoted form of managedHistoryPath & " " & quoted form of statePath
end assertRestoredManagedHistory

on captureWindow(captureScript, outputPath)
	set captureError to ""
	repeat 10 times
		try
			do shell script "rm -f " & quoted form of outputPath
			do shell script captureScript & " " & quoted form of "Basil Validation" & " " & quoted form of "" & " " & quoted form of outputPath
			do shell script "test -s " & quoted form of outputPath
			return
		on error messageText
			set captureError to messageText
			delay 0.2
		end try
	end repeat
	error "Failed to capture non-empty managed-history evidence: " & captureError
end captureWindow
