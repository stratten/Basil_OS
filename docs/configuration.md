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

For direct-provider models, use the provider's configuration area to supply a key. The current supported environment-variable examples are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY` (`GEMINI_API_KEY` is accepted as an alternative); Basil also supports user-provided keys, which it stores in the macOS Keychain, in the same single item that holds your sign-in and connection tokens, rather than in a file. A provider's enablement control is distinct from the choice to use your own API key. The latter is an explicit bring-your-own-key path, not a second provider-enable switch.

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

The Companion has no page in Settings. Its controls live in the Companion pane of the Notetaker, and they are not part of Meeting/Call Detection. They are the Companion switch, **Turn on for every new meeting**, speaking mode, optional focus, **Research automatically**, standing watches, attached context sources, and follow-up action permissions, including **Let my watches start actions without asking**. Until you choose which actions a watch may start, every proposed action waits for your approval. The Companion uses the model chosen in its pane, or the default reasoning model when none is chosen.

### Capture

Capture settings contain Activity Capture and Memories controls. Configure sources, exclusions, processing, retention, cleanup, and storage limits before enabling background collection. The selected processing model determines whether collected material remains local or can be sent to an external provider.

Choose exclusions and retention before enabling Activity Capture, because background collection can create local records over time. A start-at-launch choice affects a future app launch; it is not a replacement for reviewing the current runtime state.

## System

### Connections

Connections has two subareas:

- **MCP:** add, authorize, inspect, and remove Model Context Protocol connections.
- **ACP:** configure Agent Client Protocol provider profiles.

Connection flows can open device authorization or provider sign-in steps. A connected service can access only the authorization it receives from its provider; Basil does not make a connection usable until its configuration completes. Review each provider's terms and scope before authorizing it.

You can also ask the agent to connect a service without opening Settings. If the service signs in through a browser, the agent starts that sign-in after you approve it. If the service gives you a bearer token or API key instead, Paprika shows the same kind of overlay it uses for command approval, naming the exact host the token will go to. You paste the token there and can edit the connection's name and description in the same overlay, which matters when you connect the same service more than once, for example two accounts or workspaces. A name that is already in use is refused. The task thread keeps a record of the request, that you entered a token, and whether the service accepted it, without showing the token. Basil saves it in the Keychain vault and checks that the service accepts it by fetching its tool list, and a rejected token leaves nothing behind. The token never enters the chat, the model's context, or the conversation history. If you paste a service's setup prompt for agents into the chat, the agent takes only the server address and name from it. A token pasted into the chat itself is already in that conversation, so replace it with a fresh one.

Removing a connection prevents future use through that configuration, but it does not retroactively undo an action already sent to the connected service. Revoke the provider-side authorization as well when that is appropriate for the service.

#### Gmail with your own Google client

Basil can sign in to Gmail with a Google Cloud OAuth client that you create, instead of the client shipped with Basil. Google limits each Cloud project that has not completed verification to 100 people over its whole lifetime and shows an "unverified app" screen, and that limit applies per project. A project you own and use only for yourself needs no verification, so this is the way to use Gmail before a shared client is verified, or if you prefer not to rely on one.

1. In the Google Cloud console, create a project and enable the Gmail API for it.
2. Under Google Auth Platform, configure the consent screen with the External audience, and add the scope `https://www.googleapis.com/auth/gmail.modify` on the Data Access page.
3. Publish the app so its status is In production. A project left in Testing issues sign-in tokens that Google expires after seven days, which would make you reconnect every week. An unverified published project is fine for personal use and shows the unverified app screen at sign-in.
4. Under Clients, create an OAuth client of the type Desktop app and download its JSON file.
5. Save that file as `~/.basil/secrets/gmail_mcp_oauth_client.json`. To keep it somewhere else, set the `BASIL_GMAIL_OAUTH_CLIENT_FILE` environment variable to its path.
6. Restart Basil, then add the Gmail connection in Settings, under Connections, and sign in. On the unverified app screen choose Advanced, then continue to your app.

A client file in `~/.basil/secrets` takes precedence over the client shipped with Basil, and the environment variable takes precedence over both. Delete the file to go back to the shipped client. Basil asks for the `gmail.modify` scope, which reads mail, writes drafts, changes labels, moves messages to Trash, and sends drafts you approve, and which cannot delete mail permanently. To use Google's hosted Gmail MCP server instead of the Gmail API, choose Hosted under the Gmail connection mechanism in Settings, under Connections, or set `BASIL_GMAIL_TRANSPORT=mcp`, which overrides the Settings choice. Both mechanisms use the same `gmail.modify` sign-in, so switching never requires signing in again, and Google serves the hosted endpoint only to projects enrolled in its Developer Preview Program.

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

Basil Cloud exists to make Basil more accessible to people who would rather not set up an account with a model provider. It is not a revenue source. Each request is priced at the provider's own charge plus 20%, which is intended to cover little more than the operator's costs, such as payment-card and routing fees. Usage is invoiced to the payment method on file once what you owe reaches $10, and any smaller balance is invoiced after the month ends once it reaches $0.50, the minimum Stripe can charge. Anything below that carries forward to a later invoice.

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
