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

You can supply direct provider keys through the process environment, including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` (or `GEMINI_API_KEY`), or through Basil's provider-key settings, which store the key in the macOS Keychain, in the same single item that holds your sign-in and connection tokens. Choose only providers whose data handling is acceptable for the content you submit.

### Basil Cloud

Basil Cloud is not required for local-model or direct-key operation. If you select Basil Cloud, Basil sends selected model requests to the endpoint configured by `BASIL_AUTH_SERVICE_URL` (or Basil's default Cloud endpoint when that variable is unset). The request includes the selected provider and model, message content, sampling settings, and an authorization token. Cloud transcription routes submit the audio being transcribed to the selected Cloud path. If the configured endpoint is unavailable, that selection reports an error; it does not prevent local-model or direct-provider use.

### Custom model endpoints

Custom model configurations are a separate model path. When you select one, the endpoint or runtime you configured receives the request content necessary for that model operation. Treat a custom endpoint as an external data boundary unless you operate and trust it as a local runtime.

## Capability data flows

### Workspaces, conversations, and Paprika tasks

Basil Board inquiries, conversations, Dill outputs, Paprika task inputs, task status, and todo records can be stored locally so the corresponding workspace can be reopened. Paprika task requests can include text, selected files, pasted images, screen captures, audio, and context the user explicitly supplies. A local model keeps that material on the Mac for inference; a selected direct-provider, custom endpoint, or Basil Cloud path receives the content needed to perform that request.

Paprika tasks can prepare actions involving local files, browser automation, desktop automation, commands, and connected services. The request alone does not authorize an external side effect: Basil's approval and authorization controls remain the boundary. Review the action target and requested capability before approving it.

Local artifact previews are previews of task-produced local material. Treat an artifact's source, contents, and destination as part of the task's privacy boundary, especially when a later action proposes opening it in another application or sending it to a connected service.

### Capture, transcription, and meetings

Screen/window capture and OCR process the captured visual content locally unless you submit it to a non-local model path. Live transcription records microphone audio only after you start the recording flow; audio-file transcription reads only the local file you select. Stored transcription and audio history can contain private content.

Meeting/Call Detection is different from meeting recording. Its passive CoreAudio probe only identifies non-excluded processes that currently have both input and output audio activity; it does not create an audio tap or record audio. A meeting recording starts only after you choose the prompt action or configure the detected-meeting flow to auto-start. Calendar access can provide meeting title, attendees, calendar matching, and join prompts when a joinable event is available.

Activity Capture can create local capture records on its configured schedule. Its source, exclusions, retention, cleanup, and processing model are user-configurable. If its selected processing path uses a provider-backed model, the capture content needed for processing follows that model path's data boundary.

Meeting recordings, transcripts, speaker labels, metadata, and analysis can all contain sensitive material. Improving a transcript or running analysis with a provider-backed model can send the relevant meeting content to that selected provider. Disable or change the model path before processing material you do not want to leave the Mac.

The Notetaker Companion is optional and runs only while it is turned on. While it runs, it sends recent transcript text, the notes it has shown, and any attached-source text it needs to the selected reasoning model, once per check and again for chat, research, and audits. If that model is provider-backed, those requests follow the provider's data boundary, and a local model keeps them on the Mac. Research is read-only over attached files and Basil records. Transcript, file, and chat text is treated as data, never as instructions, so it cannot start an action by itself: every proposed to-do or agent task waits for your approval unless a watch you created is explicitly allowed to start it. The Companion's notes, its record of each check, audit results, and your Good catch and Not needed marks are saved with the meeting in `companion.json` and are removed when you delete the meeting.

Text replacement rules affect newly inserted transcription text. They do not retroactively rewrite an existing transcription record, which means historical text may retain the wording produced when it was stored.

## Optional connected services and automation

Connected services are optional. When you connect an account and invoke a related feature, Basil can make requests to that service using the authorization you granted. Agent tasks, browser automation, Apple Events, shell commands, and desktop automation can act on the content and permissions you explicitly authorize; review the proposed action and approval controls before allowing an external or destructive operation.

Calendar and Contacts access is optional. Calendar data can enrich or gate detected meetings and can identify joinable events for meeting prompts. Contacts data is used only when Contacts personalization is enabled, such as identifying recipients and adapting drafts to known names and organizations.

MCP connections and ACP provider profiles have their own provider-specific authorization flows. Connecting a service does not authorize every possible action through it, and disconnecting a service stops future use through that Basil configuration but does not revoke authorization already granted at the provider. Revoke provider-side access separately when appropriate.

Gmail is served by Basil itself, which calls Google's Gmail API directly from your Mac with the access token held in your Keychain. Basil requests the `gmail.modify` scope, which allows reading mail, writing drafts, changing labels, moving messages to Trash, and sending, and which cannot delete mail permanently. Message content that an agent task reads is sent to the model provider you configured, as with any other tool result. Every Gmail tool that changes your mailbox asks for your approval unless you switch that tool to always allow in Settings, and Basil does not store mail beyond the task history of the run that read it. Basil is a local client application for Gmail: mail is fetched, processed, and stored only on your Mac, Basil never sends your Google tokens to any server the Basil project operates, and mail content goes only to the model provider you selected, as part of completing a request you made. If you select Basil Cloud as that provider, the model requests that carry mail content go to Basil Cloud as described under Basil Cloud above; choose a local model or your own provider key to keep mail content off Basil-operated servers. Basil does not use Google user data to train or improve a generalized AI model, and you should check that your chosen provider's terms do not either. If you prefer not to use the Google client shipped with Basil, you can sign in with a Google Cloud project of your own, as described in [Configuration](configuration.md).

## Update checks

Basil checks for updates through Sparkle. A website build requests Basil's website feed, and a build downloaded from this repository requests the `update-feed` release on GitHub. Each check is an ordinary HTTPS request, so the server sees your IP address and the user agent Sparkle sends, which names Basil and its version. Basil does not enable Sparkle's system-profile reporting. If you accept an update, Basil downloads the new app from the same host and checks its signature before installing it. Choose Check for Updates in the Basil menu to check on demand.

## Local storage

The following locations are used by the current desktop/backend implementation. They can contain private information and should be included in any backup, deletion, or incident-response decision. These are application roots, not a promise that every capability writes to every location on every use.

- `~/.basil/knowledge_base.db` stores Basil's local SQLite knowledge data, including conversation, Agent Task, transcription, memory, and related application records.
- `~/.basil/config/preferences.json` stores Basil preferences; `~/.basil/config/api_key_flags.json` records only which providers use your own key, never the key itself. Provider key values are stored in the macOS Keychain, in the single item (account `com.basil.mcpTokenVault`) that also holds your sign-in and connection tokens, so macOS asks for Keychain access once. Only the Basil app reads and writes that item; the backend receives your provider keys from the app over the local connection and keeps them in memory. Earlier versions stored each key as its own item under the service `com.basil.providerKeys`; Basil moves those keys into the single item the first time it runs and removes the old items. Earlier versions kept keys in a plain-text `~/.basil/config/api_keys.json`; current versions do not read that file, do not migrate it, and it can be deleted.
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
- Stop Meeting/Call Detection or Activity Capture from its dedicated control before changing its data or runtime configuration.
- Remove local data or models only after deciding which of the storage roots above you want to delete. Close Basil before manual deletion so the backend does not recreate or write to the path during the operation.

This document describes Basil's application data paths and explicit request flows. It does not replace the privacy, retention, security, or account policies of an AI provider, a connected service, Apple, or a repository host.
