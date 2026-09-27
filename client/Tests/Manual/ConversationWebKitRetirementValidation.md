# Conversation WebKit QA Gate

## Preconditions
- The user restarted the normal local backend and confirmed that no audio capture, transcription, or Agent Task is active.
- The BasilClient build under test contains the staged `BasilBoardWebAssets/src/entries/conversation.html` entry.
- Use the label `WebKit QA gate 2026-08-03` in every created Conversation title or first user message.
- Do not approve any external action. If an Agent Task requests an approval, verify that the canonical Agent Task surface opens, reject the approval, and record the rejected state as the expected safety result.

## Automated evidence
- Backend Conversation and Basil Board tests pass.
- BasilBoard Vitest suite and production Vite build pass.
- Debug and release BasilClient builds pass.
- Focused native Conversation host, presentation coordinator, detached-thread, audio retention, and plain-text paste tests pass.

## Live native checklist
1. Open Conversation from the status menu and from its configured hotkey. Both actions show or focus one standalone WebKit Conversation window.
2. Open Basil Home, activate Chats, then open standalone Conversation. Confirm Board Chats becomes unavailable while standalone is visible. Close or minimize standalone and confirm Board Chats becomes available again.
3. Verify standalone close, minimize, collapse, expand, resize, move, reopen, and focus behavior. Reopen after collapse and confirm the normal expanded geometry is retained.
4. Verify source-symbol sidebar actions, compact header geometry, minimal focus rings, matching bubble/send blue, rounded Stop, pulsing thinking dots, source-icon copy actions, visible copy feedback, and compact recording controls in Board and standalone Conversation.
5. Send a direct message labeled `WebKit QA gate 2026-08-03`. Verify Local Models, API Models, and Custom Models are grouped in the picker; send with an installed local model and confirm its display name follows the assistant timestamp after reload.
6. Start a long direct response, invoke Stop once, confirm the control reads `Stopping` without moving nearby controls, then reload and confirm the partial or cancelled response remains without duplication.
7. Attach one harmless local text file with the picker, drag the same file over the composer, paste one small PNG, and remove each attachment before submitting. Verify picker, drag target, staged paste, attachment chips, and server response error presentation.
8. Record a brief voice prompt beside an existing formatted draft and attachment, stop recording, and verify its transcription is inserted without clearing either. Start another recording and cancel it; verify the composer remains usable.
9. Use Command-Shift-V with formatted text in the Conversation editor and verify only plaintext is inserted, the selection is replaced, React draft state updates, ordinary Command-V remains rich, and image-only paste still stages an attachment.
10. Submit a non-side-effecting request that delegates to an Agent Task. Verify immediate `Preparing agent task`, meaningful progress, the canonical deep link, terminal provenance retained above the narrated response, and no duplicate approval or task-report renderer. In a separate turn cancel narration, then reload and verify partial narration and cancellation state remain. Repeat with `Conversation only` selected and verify a direct streamed response.
11. Double-click an assistant response from Board and use its separate-window icon from global standalone. Verify one interactive window per conversation, focus-on-repeat, composer/model/attachment/voice/cancellation operation, source transcript preservation, and Board Chats remains unavailable until every standalone and thread window is closed or minimized.
12. With no active capture and after the Agent Task has durable linkage, perform the user-managed backend restart. Reopen the same Conversation and confirm durable history, Agent Task state, and narration-recovery behavior remain coherent.
13. Search for the labeled Conversation, load more history when the button is offered, then delete the labeled Conversation records. Verify no duplicate rows, literal search text, terminal-page button removal, retained results after a failed append retry, refreshed list, and server-search removal.
14. Open two conversations labeled `WebKit QA gate 2026-08-03` in the same standalone window (or one standalone plus one detached thread window). Start a long, non-side-effecting direct turn in the first, then immediately select the second and start a second long turn. Verify both stream independently, navigation and search remain responsive throughout, only the currently selected thread's Stop control is visible, and the inactive thread's delete control remains enabled while its own delete control is hidden. Attempt to submit a second message into the still-streaming first thread and verify it is rejected with `A response is already active for this conversation.` without duplicating its assistant placeholder. Use Stop on the second thread from a different window than the one that started it and verify every open window reflects the cancellation. Finally, with no active capture, perform the user-managed backend restart, reopen the still-active first conversation, and confirm its durable partial content and terminal state are coherent (no stuck 'active' indicator survives the restart).

## Result criteria
- Mark this document passed only when every numbered check produces the stated result or a documented existing non-Conversation defect with reproduction evidence.
- A failed direct stream, missing local model, duplicate surface, lost durable state, broken bridge callback, missing staged asset, detached-thread regression, or renderer regression blocks retirement. Legacy SwiftUI archival remains blocked until this checklist and automated evidence pass.
