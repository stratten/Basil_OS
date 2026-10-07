# Configuration

Open Settings from the Basil menu to configure the application. Settings are grouped into General, Personalization, Capabilities, and System. A setting can make a capability available without starting its background runtime; use the capability's dedicated control when the interface says it must be started separately.

This guide distinguishes three kinds of choice that often appear together in Settings. A capability setting changes how a feature behaves. A model or provider choice determines where model work runs and what data boundary applies. A permission, account, connection, or approval remains a separate gate even after a feature has been enabled.

## Settings map

- **General:** Home and Hotkeys.
- **Personalization:** Profile, Personal Context, and Writing Examples.
- **Capabilities:** Models, Automation & Agents, Transcription, Notetaker, and Capture.
- **System:** Connections, Permissions, Account, and Appearance & Format.

Several sections expose a second navigation level:

- **Models:** Reasoning and Transcription.
- **Automation & Agents:** Settings, Browser, Skills, and Proactive.
- **Transcription:** Settings, History, and Replacements.
- **Capture:** Activity Capture and Memories.
- **Connections:** MCP and ACP.
- **Permissions:** Application and Command Security.

## General

### Home

Home collects high-level launch and capability controls, including background behavior when supported. It can expose start-at-launch preferences for Activity Capture and Meeting/Call Detection. A start-at-launch preference applies on a future Basil launch; it does not retroactively create a monitor in an already-running process.

Use Home to review the broad application state, then use the capability-specific section to change detailed behavior. If a monitor is already running, changing a future-launch preference does not silently replace the active runtime.

### Hotkeys

Hotkeys control global shortcuts for supported actions such as transcription and capture. Your bindings are configurable. Do not rely on examples in documentation as fixed shortcuts. Input Monitoring permission is required for global key observation.

## Personalization

### Profile

Profile stores optional identity, organization, tone, and instruction fields used to personalize assistance. Leave fields empty when you do not want them available to a model request or local workflow. Review the profile before selecting a provider-backed model path if the request could use that information.

### Personal Context and Writing Examples

Personal Context configures context/memory behavior, and Writing Examples stores examples that can guide drafting style. These are local settings and records, but they may become part of a selected provider or Cloud request when that is necessary to fulfill the request.

These sections do not cause Basil to collect new information on their own. Activity Capture and Memories have their own controls under Capabilities → Capture.

## Capabilities

### Models

Models are organized by capability:

- **Reasoning:** local models, direct API/provider models, and custom models.
- **Transcription:** local and API/provider models where supported.

Select the capability first, then choose the available local, provider, or custom path. Download local models only when you have enough storage and the capability requires them. Local model files are stored under `~/.basil/models/`. Removing a local model removes its managed copy and related cache material so that a later use requires a fresh download.

For direct-provider models, use the provider's configuration area to supply a key. The current supported environment-variable examples are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`; Basil also supports user-provided keys, which it stores in the macOS Keychain rather than in a file. A provider's enablement control is distinct from the choice to use your own API key. The latter is an explicit bring-your-own-key path, not a second provider-enable switch.

Custom models are configured separately from local and provider catalogs. Use only endpoints and runtimes you trust with the content sent to them. For an OpenAI-compatible custom model, the Server Type setting tells Basil what is behind the endpoint: choose Ollama so Basil sends the model's context window to Ollama when it loads the model, and leave the default for other servers, which use the context length they were started with. Choosing a model path affects a request only when that capability uses the selection; it does not convert previously stored local data or rerun historical work.

### Automation & Agents

The Automation & Agents area contains:

- **Settings:** default reasoning and agent behavior.
- **Browser:** browser automation controls.
- **Skills:** reusable agent guidance and skill reconciliation.
- **Proactive:** proactive-suggestion settings.

Use these controls to choose how a supported workflow is offered, not to authorize an action in advance. Browser and desktop automation can require Accessibility, Apple Events, Screen Recording, account access, an active connection, and action-specific approval. Skills can shape authorized agent work but do not grant access to a system that has not been connected or approved.

### Transcription

Transcription includes settings, history, and text replacements. Configure the transcription model, behavior after a transcription completes, and replacement rules used before text is inserted. History is a separate retrieval surface for reviewing, copying, playing back recorded audio where present, and retranscribing with an available model.

Manage a replacement rule in the stable entry area above the saved-rule list. Adding, changing, or removing a replacement affects newly inserted transcription text; it does not rewrite an existing history record.

### Notetaker

Notetaker configures Meeting/Call Detection:

- Enable or disable detection.
- Choose `prompt` or `auto_start` behavior.
- Set probe cadence and per-app cooldown.
- Enrich detections from Calendar or require a calendar match.
- Configure automatic ending after inactive audio when enabled.
- Exclude applications by bundle identifier or application name.

Enabling Meeting/Call Detection makes the monitor available. Start or stop the current monitor from the Basil menu unless the separate start-at-launch preference is enabled. Calendar matching reduces false positives, particularly for browsers, but can omit calls that have no active calendar event.

The setting does not start recording. In `prompt` mode, you decide whether a detected call should create a meeting. In `auto_start` mode, Basil follows the detected-meeting configuration. While a meeting is preparing or recording, the detection flow suppresses later launch panels so that only one meeting can be active.

### Capture

Capture settings contain Activity Capture and Memories controls. Configure sources, exclusions, processing, retention, cleanup, and storage limits before enabling background collection. The selected processing model determines whether collected material remains local or can be sent to an external provider.

Choose exclusions and retention before enabling Activity Capture, because background collection can create local records over time. A start-at-launch choice affects a future app launch; it is not a replacement for reviewing the current runtime state.

## System

### Connections

Connections has two subareas:

- **MCP:** add, authorize, inspect, and remove Model Context Protocol connections.
- **ACP:** configure Agent Client Protocol provider profiles.

Connection flows can open device authorization or provider sign-in steps. A connected service can access only the authorization it receives from its provider; Basil does not make a connection usable until its configuration completes. Review each provider's terms and scope before authorizing it.

Removing a connection prevents future use through that configuration, but it does not retroactively undo an action already sent to the connected service. Revoke the provider-side authorization as well when that is appropriate for the service.

### Permissions

The Application section reports and links to macOS permissions. The Command Security section manages approval-oriented controls for commands and automation. Grant only the minimum permissions needed for your intended workflow:

- Microphone for live audio capture.
- Input Monitoring for global hotkeys.
- Accessibility and Apple Events for desktop automation.
- Screen Recording for screen/window capture and visual analysis.
- Calendar for meeting enrichment, join prompts, and calendar-matched detection.
- Contacts for optional personalization workflows.

Revoking a permission leaves unrelated capabilities available but prevents the dependent capability from operating. Some permission changes take effect only after macOS or the app restarts the relevant process; Screen Recording is the common example. The user-facing prompt and macOS System Settings remain the authority for whether access is granted.

### Account

Account manages sign-in, sign-out, account deletion, payment setup where available, usage display, and the preferred model-access path. Basil Cloud is optional: local-model and direct-provider configurations do not require a Basil Cloud account. Basil Cloud requires an authenticated account with a payment method on file; that requirement is an account concern and does not replace a direct-provider key or local model.

Sign out or remove account authorization when you no longer intend to use a Cloud-backed path. Your local models and direct-provider configuration remain separate choices, although removing an account can make its Cloud model path unavailable.

### Appearance & Format

Appearance & Format controls the application theme, fonts, colors, surface finish, and other presentation choices supported by the active UI. These are local presentation preferences and do not affect model behavior, provider data handling, permissions, or connections.

## Provider and data choices

Choose the model path per capability:

- **Local:** inference runs on your Mac.
- **Direct provider:** Basil sends the content required for the selected request to the configured provider using your key.
- **Custom:** the configured model runtime or endpoint receives the content required for the request.
- **Basil Cloud:** the selected request is sent to the configured Basil Cloud endpoint with its account authorization.

When a capability offers more than one path, select the smallest boundary that fits the work: a local model for local inference, a direct provider when you intend to use your key and accept that provider's terms, a custom endpoint only when you trust the endpoint, or Basil Cloud when you intend to use the account-backed path.

Read [Privacy and data flow](privacy-and-data-flow.md) before selecting a provider or connecting a service. See [Capabilities](capabilities.md) for feature-level dependencies and limitations.
