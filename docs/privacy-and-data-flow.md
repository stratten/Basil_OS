# Privacy and data flow

Basil is a macOS desktop assistant with a local Swift client and a local Python backend. A community build can run with local models or with keys that you provide directly to an AI provider. Basil Cloud is optional.

## Choose your model path

### Local models

When you select a local model, Basil performs inference on your Mac. The text, audio, images, and files used for that request stay in the local application process unless you separately use a connected service, browser automation, or another feature that contacts an external system. Downloading a local model requires contacting its configured model host to retrieve the model files.

### Bring your own provider key

When you select a direct provider model, Basil sends the request content needed by that model to the selected provider. This can include conversation messages, prompts assembled from files or application context that you explicitly provide, screenshots or image content selected for vision work, and audio submitted for cloud transcription. The provider receives the request under its own terms and privacy policy. Basil sends the provider credential with the request; it is not included in this repository.

You can supply direct provider keys through the process environment, including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`, or through Basil's local provider-key settings. Choose only providers whose data handling is acceptable for the content you submit.

### Basil Cloud

Basil Cloud is not required for local-model or direct-key operation. If you select Basil Cloud, Basil sends selected model requests to the endpoint configured by `BASIL_AUTH_SERVICE_URL` (or Basil's default Cloud endpoint when that variable is unset). The request includes the selected provider and model, message content, sampling settings, and an authorization token. Cloud transcription routes submit the audio being transcribed to the selected Cloud path. If the configured endpoint is unavailable, that selection reports an error; it does not prevent local-model or direct-provider use.

## Optional connected services and automation

Connected services are optional. When you connect an account and invoke a related feature, Basil can make requests to that service using the authorization you granted. Agent tasks, browser automation, Apple Events, shell commands, and desktop automation can act on the content and permissions you explicitly authorize; review the proposed action and approval controls before allowing an external or destructive operation.

Calendar and Contacts access is optional. Calendar data is used to title and enrich detected meetings. Contacts data is used only when Contacts personalization is enabled, such as identifying recipients and adapting drafts to known names and organizations.

## Local storage

The following locations are used by the current desktop/backend implementation. They can contain private information and should be included in any backup, deletion, or incident-response decision.

- `~/.basil/knowledge_base.db` stores Basil's local SQLite knowledge data, including application content such as saved transcription and conversation-related records.
- `~/.basil/config/preferences.json` stores Basil preferences; `~/.basil/config/api_keys.json` can store user-provided provider keys.
- `~/.basil/data/` holds runtime data and capture-related working files. `BASIL_DATA_DIR` overrides the backend data-directory default for components that use the shared API settings.
- `~/.basil/models/` holds downloaded local model files. `BASIL_MODELS_DIR` overrides its shared API-settings default.
- `~/.basil/meetings/` holds meeting recording and analysis material organized by meeting identifier.
- `~/.basil/runtime/` holds local backend runtime status material.
- `~/.config/basil/` holds setup-assistant state and voice-listener settings.
- `~/Library/Application Support/Basil/` is used by the non-development macOS storage service for captures, processed files, temporary files, and its SQLite database.

Some legacy or specialized components use their own compatible paths while Basil migrates storage. The paths above are the relevant roots to inspect before deleting data. Removing a model or local data can make prior conversations, transcriptions, meeting material, and downloaded models unavailable.

## macOS permissions

Basil requests or checks permissions through macOS. Declining a permission leaves features that do not need it available, but disables the feature that does.

- **Microphone:** records microphone audio for transcription.
- **Input Monitoring:** observes global keyboard events for configured hotkeys.
- **Accessibility:** inserts text and controls user-interface elements for desktop automation.
- **Apple Events / Automation:** controls other applications when you use automation features.
- **Screen Recording:** captures screen or window images for OCR and visual analysis.
- **Calendar:** reads calendar information to title and enrich detected meetings.
- **Contacts:** supports optional Contacts personalization for drafts and recipient identification.

The setup flow presents microphone, Accessibility, Input Monitoring, Screen Recording, and Apple Events permission controls. Do not assume permission requests occur only at the moment a particular feature is first used. You can revoke or change any of these permissions in macOS System Settings → Privacy & Security. Basil provides deep links to the relevant privacy panes for microphone, Accessibility, Input Monitoring, Automation, and Screen Recording.

## Controls and revocation

- Stop using a provider or Basil Cloud by selecting a local model or another configured provider, then remove the relevant provider key or Cloud authorization from local settings.
- Disconnect optional connected services from Basil and revoke their authorization at the provider when appropriate.
- Revoke macOS permissions in System Settings → Privacy & Security.
- Remove local data or models only after deciding which of the storage roots above you want to delete. Close Basil before manual deletion so the backend does not recreate or write to the path during the operation.

This document describes Basil's application data paths and explicit request flows. It does not replace the privacy, retention, security, or account policies of an AI provider, a connected service, Apple, or a repository host.
