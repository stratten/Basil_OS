# Package 5A.1 Manual Verification: Native Workspace-Directory Bridge

## Prerequisites

Build and run BasilClient locally, open the BasilBoard window, and open Safari's Web Inspector against BasilBoard's WKWebView (Safari > Develop > [device] > BasilBoard).

## Steps

1. In the Web Inspector console, run `const previousWorkspaceCallback = window.basilBoardBridge.onWorkspaceDirectoryPicked; window.basilBoardBridge.onWorkspaceDirectoryPicked = (payload) => { console.log(payload); previousWorkspaceCallback?.(payload); };` to log the native response without suppressing the installed bridge handler.
2. Run `window.webkit.messageHandlers.basilBoardBridge.postMessage({ type: 'pickWorkspaceDirectory', requestId: 'manual-1' })`.
3. Confirm a native "Choose Workspace Folder" panel opens, showing folders only (no files selectable and directory creation unavailable).
4. Select an existing folder and confirm the logged payload is `{ requestId: 'manual-1', status: 'selected', path: '<the folder's real, symlink-resolved absolute path>' }`.
5. Repeat step 2 with a new `requestId`, then click Cancel. Confirm the logged payload is `{ requestId: '<id>', status: 'canceled' }` with no `path` field.
6. Repeat step 2 targeting a folder inside `/tmp` that is itself a symlink (create one with `ln -s /tmp/real-target /tmp/link-target` in Terminal first) and confirm the returned `path` is the real, non-symlink target.
7. Run `window.webkit.messageHandlers.basilBoardBridge.postMessage({ type: 'pickWorkspaceDirectory', requestId: '' })`. Confirm no panel opens and no callback is produced, proving malformed bridge values are rejected without crashing the host.
