# Capabilities

This guide describes the user-facing functionality currently implemented in Basil. It is organized around what you can open or configure in the application, what the capability normally produces, where relevant results are retained, and the boundaries that remain in effect. Availability depends on macOS permissions, selected models, account mode, configured provider keys, connected services, and the capability-specific settings you enable.

## How to read this guide

Basil uses four kinds of gate. A feature can require a model, a macOS permission, an account or external connection, and an approval for a specific action. Enabling a setting does not bypass another gate, and a request does not authorize an external side effect by itself.

Local records remain on the Mac unless you select a model or service path that sends the request content elsewhere. The [Privacy and data flow](privacy-and-data-flow.md) guide identifies the principal storage roots and provider boundaries.

## Workspaces and assistance

### Basil Board

Start in the Basil Board when you want a single workspace for an inquiry. The Board brings together inquiry history, conversations, Agent Tasks, meeting state, and the todo workspace. It accepts text, voice, files, and images when the selected model and the relevant permission support that input.

The immediate result is an inquiry or workspace item you can continue, revisit, or hand off to another Basil surface. Conversations may stay inside the Board or open in their own window. Board-related inquiry, conversation, task, and todo data can be retained locally so work can be reopened.

The Board is not an elevated permission surface. A request that needs a connection, browser action, desktop automation, command, or other side effect still follows the configured model, authorization, and approval flow.

### Conversations

Open or create a conversation from the Board when you want a durable thread around a subject. Conversations retain threaded messages and use the reasoning model path currently available to the application. They are suitable for continuing work rather than treating every prompt as an isolated request.

Conversation messages and associated records can be stored locally for later retrieval. A local reasoning model keeps inference on the Mac; direct-provider, custom-endpoint, and Cloud selections can receive the request content needed to answer. Deleting local data can make previously saved threads unavailable.

### Assistant Session

Open Assistant Session when you want a focused text-or-voice assistant instead of a Board workspace. It provides saved output history plus controls to copy, refine, edit, or save the response as your workflow requires.

Assistant Session requires a usable reasoning model. Its saved outputs are local application history, subject to the local-data lifecycle described in [Privacy and data flow](privacy-and-data-flow.md). A provider-backed model path changes the data boundary for the content used to produce the output, but it does not grant automation or connected-service permission.

### Agent Tasks

Start an Agent Task from a Board or task-oriented workflow when the request needs an explicit goal, progress visibility, revisions, tool use, or a result that may include a local artifact. A task can accept typed text, captured audio, files, images, and screen context. It can show intermediate activity, status, results, local artifact previews, and approval-controlled actions.

Tasks can be associated with Board or conversation context, scheduled for later work, reviewed after completion, and paused or canceled when their state supports those operations. The task record and its local artifacts can be retained so you can reopen the result.

An Agent Task may use local or provider-backed models and connected tools, but the task request does not itself permit an external action. Basil continues to require the relevant connection, account, permission, and explicit approval before sending a message, modifying a third-party record, running a command, or taking another consequential step.

### Todo workspace

Use the todo workspace in the Board to organize work that is not finished in a single interaction. It provides inbox, open, in-progress, ready-for-review, and completed views, along with details, dates, ordering, deletion, and work-status displays for agent-backed work.

Todos are local organizational records that can be reopened and updated. They can describe planned agent work, but they do not authorize the agent to perform an external action or override a safety gate.

## Capture and transcription

### Screen and window capture

Use the capture control, the Board, or a configured hotkey to capture screen or window content for OCR, visual analysis, and context-assisted work. The normal result is captured visual material that can be inspected locally or included in a model-backed request.

Screen Recording permission is required for actual capture. Capture content can be private and may become part of the selected model request. A local model processes it on the Mac; a direct provider, custom endpoint, or Cloud model can receive the content required to perform the request.

Hotkeys are configurable. Documentation examples are examples only and do not guarantee a particular binding on your installation.

### Live transcription

Open the transcription widget to record microphone audio and receive a live transcript. Settings control the transcription model, post-completion behavior, paste behavior, history, and text-replacement rules applied before text is inserted.

The normal result is transcription text that can be reviewed, copied, pasted, or stored in history. History can retain the transcript and, when recorded audio exists, support audio playback and retranscription with an available model.

Microphone permission is required to record live audio. Selecting a local transcription model keeps inference on the Mac; provider-backed transcription paths can receive the audio or text needed to perform the request.

### Audio-file transcription

Use the audio-file transcription flow to choose a local audio file and transcribe it with an available model. Basil reads the file you select; it does not scan arbitrary files to find audio.

The resulting transcript follows the same history, review, copy, and retranscription workflow as live transcription where the relevant data is available. A provider-backed transcription choice changes the data boundary for the selected file's audio content.

### Text replacements

Manage text replacements in Settings → Transcription → Replacements. The entry area defines replacement rules, and the saved rules appear below it so the control stays in a stable location as the list grows.

Replacements apply before Basil inserts newly transcribed text. Editing a rule affects future insertions; it does not rewrite an already stored transcript or silently modify historical data.

## Meetings

### Meeting Assistant

Open **Meeting / Call Transcription** from the Basil menu to create a manual recording. Before recording, set a meeting name, purpose, participants, and the available microphone or system-audio source. During recording, the Meeting Assistant shows source meters, recording state, and the live transcript.

After recording, meeting history lets you reopen, resume, search, filter, and delete stored meeting records. You can search the transcript, copy all transcript text, improve a transcript with a selected post-processing model, add speaker labels, and run analysis. Available analysis modes include summaries, action items, to-do candidates, key decisions, questions and answers, sentiment, and custom instructions. Analysis output can be reopened, copied, and exported as Markdown.

Meeting recordings, transcripts, and analysis are local material under `~/.basil/meetings/`. Only one meeting recording can be active at a time. A selected provider-backed post-processing or analysis model can receive the relevant meeting content, so choose that path carefully.

### Meeting Detection

Configure Meeting Detection in Settings → Meetings, then start or stop the current monitor from the Basil menu unless the separate start-at-launch preference is enabled. Detection looks for non-excluded macOS processes that are concurrently using audio input and output. It can operate in `prompt` mode, which opens a confirmation panel, or `auto_start` mode, which begins the configured detected-meeting flow.

Passive detection is not recording: the CoreAudio probe identifies process activity but does not create an audio tap or write audio. Recording starts only after you choose the prompt action or configure the detected-meeting flow to auto-start.

Calendar access can enrich a detection with meeting metadata, require an active calendar match, and present a join prompt for a joinable event. Calendar matching can reduce browser-related false positives, but it can also omit ad-hoc calls that have no current calendar event.

Only one detected-meeting launch or meeting recording is allowed at a time. While Basil is preparing or recording a meeting, later detection events are ignored and cannot open a second panel. If a detection panel is already visible, it closes when recording begins.

## Context and personalization

### Profile, personal context, and writing examples

Use Settings → Profile, Personal Context, and Writing Examples to define optional identity, organization, tone, instructions, reference context, and examples that can tailor drafting and reasoning. Leave a field empty when you do not want it available to a local workflow or a model request.

These settings and records are stored locally. They may become part of a request when you choose a provider-backed model or service path that needs them to fulfill your request. They do not independently connect an account or transmit information.

### Activity Capture and memories

Use Settings → Capture to configure Activity Capture and Memories. Activity Capture can create local records on its configured schedule, with source selection, exclusions, retention, cleanup, processing, and storage controls. Memories and personal-context workflows can organize selected material into durable context.

Review the source, retention, cleanup, and processing settings before enabling background collection. Required permissions, configured sources, and the selected processing model determine whether a workflow is available and whether content remains local or follows a provider-backed model path. The [Privacy and data flow](privacy-and-data-flow.md) guide describes storage and deletion cautions.

### Skills and reconciliation

Use Settings → Automation & Agents → Skills to work with reusable agent guidance and behavior. Skill reconciliation provides a dedicated review surface for aligning skill material when the available workflow calls for it.

Skills can influence how an agent performs work but cannot grant permissions, bypass approvals, make an unavailable model usable, or authorize an external service. Treat skill content as local guidance that remains subject to the same model and connection boundaries as the task using it.

### Setup, onboarding, and proactive suggestions

The setup and onboarding surfaces guide initial preferences, permissions, models, and connections. They help you configure an available capability; they do not silently accept a macOS permission prompt or finish a third-party authorization on your behalf.

Use Settings → Automation & Agents → Proactive to configure Proactive Suggestions. Suggestions can surface configured assistance when its runtime settings allow it. A suggestion remains assistance, not authorization for a command, external connection, or desktop action.

## Automation and integrations

### Browser and desktop automation

Use the Automation & Agents and related task workflows to configure browser automation, desktop automation, and command-oriented work. The result can be an approved action proposal or an executed action within the permissions and connections you explicitly configured.

Browser and desktop automation can require Accessibility, Apple Events, Screen Recording, application-specific permissions, an account, and action-specific approval. Review the target and action before approval. Do not grant broad permissions solely to make an optional workflow available.

### Connections, MCP, and ACP provider profiles

Use Settings → Connections → MCP to add, authorize, inspect, or remove Model Context Protocol connections. Use Settings → Connections → ACP to configure Agent Client Protocol provider profiles.

A connection flow can open a device-authorization or provider sign-in step. The connected service receives only the authorization granted through its provider flow. A provider profile describes compatible external capabilities; it does not transfer credentials or independently authorize tool use.

### Voice listener

Enable the optional voice listener or wake-word path only when you intend to use a voice-driven workflow. It requires microphone access and an enabled listener setting.

The listener is an input mechanism. It does not replace the model, permission, connection, or approval requirements for any action the resulting request attempts to take.

## Models, accounts, and settings

### Models

Use Settings → Models to choose available reasoning and transcription models. The Models area separates those capabilities into local, API/provider, and custom sources where supported. Downloaded local models are retained under `~/.basil/models/`; removing one removes Basil's managed copy and related cache material, so later use requires a fresh download.

Direct-provider models use the key you configure. Custom models use the endpoint or runtime you configure. Basil Cloud is an optional account-backed model path. Selecting a provider enablement control is distinct from selecting the explicit “use your own API key” path; the latter is not a second enable switch.

### Permissions, account, and appearance

Settings → Permissions reports and links to application permissions and provides command-security controls. Settings → Account manages sign-in, sign-out, account deletion, payment setup where available, usage display, and preferred model access. Local and direct-provider configurations do not require a Basil Cloud account.

Settings → Appearance & Format controls local presentation choices such as theme, fonts, colors, surface finish, and supported formatting preferences. Appearance changes do not change the chosen model, a provider's data handling, or a macOS permission.

For step-by-step configuration guidance, read [Configuration](configuration.md). For model and data boundaries, read [Privacy and data flow](privacy-and-data-flow.md).
