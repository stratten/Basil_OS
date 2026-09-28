# Privacy and data flow

Basil is a macOS desktop assistant with a local Swift client and a local Python backend. A community build can run with local models or with keys that you provide directly to an AI provider. Basil Cloud is optional.

## How a request crosses a boundary

Basil does not use a single data path for every feature. The chosen model path determines where model inference happens, while a connected service, browser automation, desktop automation, or command can create a separate external boundary. A feature being visible or enabled does not by itself send data to a provider or authorize an external action.

Before enabling a capability, identify the local material it will use, the model path it will use, and whether it can contact another system. Before approving an action, identify the target and the specific data or permission that action needs. This guide describes Basil's application-level behavior; it does not replace an AI provider's, connected service's, or operating system's privacy terms.

## Choose your model path

### Local models

When you select a local model, Basil performs inference on your Mac. The text, audio, images, and files used for that request stay in the local application process unless you separately use a connected service, browser automation, or another feature that contacts an external system. Downloading a local model requires contacting its configured model host to retrieve the model files.

### Bring your own provider key

When you select a direct provider model, Basil sends the request content needed by that model to the selected provider. This can include conversation messages, prompts assembled from files or application context that you explicitly provide, screenshots or image content selected for vision work, and audio submitted for cloud transcription. The provider receives the request under its own terms and privacy policy. Basil sends the provider credential with the request; it is not included in this repository.

You can supply direct provider keys through the process environment, including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`, or through Basil's local provider-key settings. Choose only providers whose data handling is acceptable for the content you submit.

### Basil Cloud

Basil Cloud is not required for local-model or direct-key operation. If you select Basil Cloud, Basil sends selected model requests to the endpoint configured by `BASIL_AUTH_SERVICE_URL` (or Basil's default Cloud endpoint when that variable is unset). The request includes the selected provider and model, message content, sampling settings, and an authorization token. Cloud transcription routes submit the audio being transcribed to the selected Cloud path. If the configured endpoint is unavailable, that selection reports an error; it does not prevent local-model or direct-provider use.

### Custom model endpoints

Custom model configurations are a separate model path. When you select one, the endpoint or runtime you configured receives the request content necessary for that model operation. Treat a custom endpoint as an external data boundary unless you operate and trust it as a local runtime.

## Capability data flows

### Workspaces, conversations, and Agent Tasks

Basil Board inquiries, conversations, Assistant Session outputs, Agent Task inputs, task status, and todo records can be stored locally so the corresponding workspace can be reopened. Agent Task requests can include text, selected files, pasted images, screen captures, audio, and context the user explicitly supplies. A local model keeps that material on the Mac for inference; a selected direct-provider, custom endpoint, or Basil Cloud path receives the content needed to perform that request.

Agent Tasks can prepare actions involving local files, browser automation, desktop automation, commands, and connected services. The request alone does not authorize an external side effect: Basil's approval and authorization controls remain the boundary. Review the action target and requested capability before approving it.

Local artifact previews are previews of task-produced local material. Treat an artifact's source, contents, and destination as part of the task's privacy boundary, especially when a later action proposes opening it in another application or sending it to a connected service.

### Capture, transcription, and meetings

Screen/window capture and OCR process the captured visual content locally unless you submit it to a non-local model path. Live transcription records microphone audio only after you start the recording flow; audio-file transcription reads only the local file you select. Stored transcription and audio history can contain private content.

Meeting Detection is different from meeting recording. Its passive CoreAudio probe only identifies non-excluded processes that currently have both input and output audio activity; it does not create an audio tap or record audio. A meeting recording starts only after you choose the prompt action or configure the detected-meeting flow to auto-start. Calendar access can provide meeting title, attendees, calendar matching, and join prompts when a joinable event is available.

Activity Capture can create local capture records on its configured schedule. Its source, exclusions, retention, cleanup, and processing model are user-configurable. If its selected processing path uses a provider-backed model, the capture content needed for processing follows that model path's data boundary.

Meeting recordings, transcripts, speaker labels, metadata, and analysis can all contain sensitive material. Improving a transcript or running analysis with a provider-backed model can send the relevant meeting content to that selected provider. Disable or change the model path before processing material you do not want to leave the Mac.

Text replacement rules affect newly inserted transcription text. They do not retroactively rewrite an existing transcription record, which means historical text may retain the wording produced when it was stored.

## Optional connected services and automation

Connected services are optional. When you connect an account and invoke a related feature, Basil can make requests to that service using the authorization you granted. Agent tasks, browser automation, Apple Events, shell commands, and desktop automation can act on the content and permissions you explicitly authorize; review the proposed action and approval controls before allowing an external or destructive operation.

Calendar and Contacts access is optional. Calendar data can enrich or gate detected meetings and can identify joinable events for meeting prompts. Contacts data is used only when Contacts personalization is enabled, such as identifying recipients and adapting drafts to known names and organizations.

MCP connections and ACP provider profiles have their own provider-specific authorization flows. Connecting a service does not authorize every possible action through it, and disconnecting a service stops future use through that Basil configuration but does not revoke authorization already granted at the provider. Revoke provider-side access separately when appropriate.

## Local storage

The following locations are used by the current desktop/backend implementation. They can contain private information and should be included in any backup, deletion, or incident-response decision. These are application roots, not a promise that every capability writes to every location on every use.

- `~/.basil/knowledge_base.db` stores Basil's local SQLite knowledge data, including conversation, Agent Task, transcription, memory, and related application records.
- `~/.basil/config/preferences.json` stores Basil preferences; `~/.basil/config/api_keys.json` can store user-provided provider keys.
- `~/.basil/data/` holds runtime data and capture-related working files, including capture folders and temporary screen/window-capture material. `BASIL_DATA_DIR` overrides the backend data-directory default for components that use the shared API settings.
- `~/.basil/models/` holds downloaded local model files. `BASIL_MODELS_DIR` overrides its shared API-settings default.
- `~/.basil/meetings/` holds meeting recording and analysis material organized by meeting identifier.
- `~/.basil/runtime/` holds local backend runtime status material.
- `~/.config/basil/` holds setup-assistant state and voice-listener settings.
- `~/Library/Application Support/Basil/` is used by the non-development macOS storage service for captures, processed files, temporary files, and its SQLite database.

Some legacy or specialized components use their own compatible paths while Basil migrates storage. The paths above are the relevant roots to inspect before deleting data. Removing a model or local data can make prior conversations, transcriptions, meeting material, and downloaded models unavailable.

### Retention, backup, and deletion

Retention is capability-specific. Activity Capture exposes retention and cleanup controls; transcription, meeting, conversation, task, and model records persist while their local storage remains available; and a provider or connected service can retain data under its own policies once you send it there.

Before a backup or migration, decide whether it should include application records, recordings, downloaded models, provider-key configuration, or all of them. Before manual deletion, quit Basil so that an active backend does not recreate runtime material while you are removing it. Deleting a local record does not retract a request already sent to a provider or connected service.

## macOS permissions

Basil requests or checks permissions through macOS. Declining a permission leaves features that do not need it available, but disables the feature that does.

- **Microphone:** records microphone audio for transcription, meetings, and optional voice-driven workflows.
- **Input Monitoring:** observes global keyboard events for configured hotkeys.
- **Accessibility:** inserts text and controls user-interface elements for desktop automation.
- **Apple Events / Automation:** controls other applications when you use automation features.
- **Screen Recording:** captures screen or window images for OCR and visual analysis; it can also provide optional window titles for meeting detection.
- **Calendar:** reads calendar information to enrich or gate detected meetings and to offer join prompts for joinable events.
- **Contacts:** supports optional Contacts personalization for drafts and recipient identification.

The setup flow presents microphone, Accessibility, Input Monitoring, Screen Recording, and Apple Events permission controls. Do not assume permission requests occur only at the moment a particular feature is first used. You can revoke or change any of these permissions in macOS System Settings → Privacy & Security. Basil provides deep links to the relevant privacy panes for microphone, Accessibility, Input Monitoring, Automation, and Screen Recording.

## Controls and revocation

- Stop using a provider or Basil Cloud by selecting a local model or another configured provider, then remove the relevant provider key or Cloud authorization from local settings.
- Disconnect optional connected services from Basil and revoke their authorization at the provider when appropriate.
- Revoke macOS permissions in System Settings → Privacy & Security.
- Stop Meeting Detection or Activity Capture from its dedicated control before changing its data or runtime configuration.
- Remove local data or models only after deciding which of the storage roots above you want to delete. Close Basil before manual deletion so the backend does not recreate or write to the path during the operation.

This document describes Basil's application data paths and explicit request flows. It does not replace the privacy, retention, security, or account policies of an AI provider, a connected service, Apple, or a repository host.
