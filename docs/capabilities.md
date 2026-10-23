# Capabilities

This guide describes the user-facing functionality currently implemented in Basil. It is organized around what you can open or configure in the application, what the capability normally produces, where relevant results are retained, and the boundaries that remain in effect. Availability depends on macOS permissions, selected models, account mode, configured provider keys, connected services, and the capability-specific settings you enable.

## How to read this guide

Basil uses four kinds of gate. A feature can require a model, a macOS permission, an account or external connection, and an approval for a specific action. Enabling a setting does not bypass another gate, and a request does not authorize an external side effect by itself.

Local records remain on the Mac unless you select a model or service path that sends the request content elsewhere. The [Privacy and data flow](privacy-and-data-flow.md) guide identifies the principal storage roots and provider boundaries.

## Workspaces and assistance

### Basil Board

Start in the Basil Board when you want a single workspace for a request. The Board brings together conversations, Paprika (Agent) tasks, meeting state, and the todo workspace. It accepts text, voice, files, and images when the selected model and the relevant permission support that input.

Home is the front door: a single input that routes each request and then forwards you to the place where the work continues. A question opens a new conversation in Chats with the message already sent. A task starts a Paprika task and opens it in the Agents tab, or in the task window if that window is already open. A short notice names where the request went and offers a one-click correction ("Send as agent task instead" or "Answer in a chat instead"). Your text stays in the box if the request could not be handed off. Below the input, Home lists your last few requests as links that reopen each one.

The immediate result is a conversation or task you can continue, revisit, or hand off to another Basil surface. Conversations may stay inside the Board or open in their own window. Board-related inquiry, conversation, task, and todo data can be retained locally so work can be reopened.

The Board is not an elevated permission surface. A request that needs a connection, browser action, desktop automation, command, or other side effect still follows the configured model, authorization, and approval flow.

### Conversations

Open or create a conversation from the Board when you want a durable thread around a subject. Conversations retain threaded messages and use the reasoning model path currently available to the application. They are suitable for continuing work rather than treating every prompt as an isolated request.

Conversation messages and associated records can be stored locally for later retrieval. A local reasoning model keeps inference on the Mac; direct-provider, custom-endpoint, and Cloud selections can receive the request content needed to answer. Deleting local data can make previously saved threads unavailable.

### Dill (Quick Assist)

Dill is Basil's Quick Assist. Each request, including each refinement, is answered in a single model turn, even when that turn does research. Its default hotkey is a double press of Option (⌥⌥). Open it when you want a focused text-or-voice assistant instead of a Board workspace. It provides saved output history plus controls to copy, refine, edit, or save the response as your workflow requires.

Dill requires a usable reasoning model. Its saved outputs are local application history, subject to the local-data lifecycle described in [Privacy and data flow](privacy-and-data-flow.md). A provider-backed model path changes the data boundary for the content used to produce the output, but it does not grant automation or connected-service permission.

### Paprika (Agent)

Paprika is Basil's agent. Unlike Dill, Paprika works through a multi-step loop with tools, progress, and approvals, and can run many tasks at once. The default capture hotkey is Option-Space (⌥Space). Start a Paprika task from that hotkey, the Board, or another task-oriented workflow when the request needs an explicit goal, progress visibility, revisions, tool use, or a result that may include a local artifact. A task can accept typed text, captured audio, files, images, and screen context. It can show intermediate activity, status, results, local artifact previews, and approval-controlled actions.

Tasks can be associated with Board or conversation context, scheduled for later work, reviewed after completion, and paused or canceled when their state supports those operations. A running task can be paused after its current step and resumed later, including after Basil restarts, and you can send it a note, with files or folders attached by path, which it reads before its next step. A task you stop shows as Canceled with a Run again action rather than as a failure, and a follow-up to a finished task continues the earlier conversation, including the files read and tools run. When a long task on a local model would exceed the model's context window, Basil shortens older material first and, if the task still does not fit, stops and reports which model ran out of context. The task record and its local artifacts can be retained so you can reopen the result.

When a task needs an answer from you, it shows an Input required request. Choosing See work so far collapses the question into a compact card so the work stays visible, and Skip leaves the same card in place, so Answer now reopens the full question with what you had entered. A question left unanswered survives restarting Basil for up to 7 days, and the header Stop button remains available while a task waits for your input. When Basil asks to approve a command, the approval shows the agent's own explanation of what it does, or warns you when none was given, together with the agent's recommendation to remember the choice or ask each time; kinds of command that can never be remembered are not offered for remembering.

The sidebar lists Tasks, Scheduled items, and an Archived view. Swipe a finished task to archive it off the Tasks list, and use Unarchive in the Archived view to bring it back. A scheduled item shows a green dot while it is active and a hollow ring while it is inactive, can be pinned to its own reasoning model (otherwise it follows the default model), records a notice in its run history when its pinned model is no longer available and the run used the default model instead, and asks for confirmation before it is deleted. A scheduled run does the work the schedule describes and cannot create further schedules, so a task that must keep checking on something schedules follow-up checks inside its own task.

A Paprika task may use local or provider-backed models and connected tools, but the task request does not itself permit an external action. Basil continues to require the relevant connection, account, permission, and explicit approval before sending a message, modifying a third-party record, running a command, or taking another consequential step.

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

The normal result is transcription text that can be reviewed, copied, pasted, or stored in history. History can retain the transcript and, when recorded audio exists, support audio playback and retranscription with an available model. Playing a recording shows a progress bar with elapsed and total time, and you can click the bar or use the arrow keys to jump to another point in the recording.

Microphone permission is required to record live audio. Selecting a local transcription model keeps inference on the Mac; provider-backed transcription paths can receive the audio or text needed to perform the request.

### Audio-file transcription

Use the audio-file transcription flow to choose a local audio file and transcribe it with an available model. Basil reads the file you select; it does not scan arbitrary files to find audio.

The resulting transcript follows the same history, review, copy, and retranscription workflow as live transcription where the relevant data is available. A provider-backed transcription choice changes the data boundary for the selected file's audio content.

### Text replacements

Manage text replacements in Settings → Transcription → Replacements. The entry area defines replacement rules, and the saved rules appear below it so the control stays in a stable location as the list grows.

Replacements apply before Basil inserts newly transcribed text. Editing a rule affects future insertions; it does not rewrite an already stored transcript or silently modify historical data.

## Meetings and calls

### Notetaker

Open **Notetaker** from the Basil menu to create a manual recording of a meeting or call. Before recording, set a meeting name, purpose, participants, and the available microphone or system-audio source. During recording, the Notetaker shows source meters, recording state, and the live transcript.

After recording, meeting history lets you reopen, resume, search, filter, and delete stored meeting records. You can search the transcript, copy all transcript text, improve a transcript with a selected post-processing model, add speaker labels, and run analysis. Available analysis modes include summaries, action items, to-do candidates, key decisions, questions and answers, sentiment, and custom instructions. Analysis output can be reopened, copied, and exported as Markdown.

While a recording runs, a small advice chip in the Notetaker appears when your Mac is running hot, low on memory, or working at its limit, or when transcription falls behind, so you can act before the recording suffers.

Meeting recordings, transcripts, and analysis are local material under `~/.basil/meetings/`. Only one meeting recording can be active at a time. A selected provider-backed post-processing or analysis model can receive the relevant meeting content, so choose that path carefully.

### Notetaker Companion

The Companion is an optional assistant that sits beside the live transcript in the Notetaker. Turn it on for one meeting from its pane, or choose **Turn on for every new meeting**. It can speak up on its own with suggestions when the topic shifts and from time to time, or stay quiet unless prompted, in which case it only answers questions and flags the topics you watch. You can give it an optional focus, such as flagging any commitment about a launch date, and ask it questions in the Companion chat while the meeting runs.

Drop a folder or file on the pane to attach it as a context source, up to five per meeting. You can also add or remove sources after the meeting has ended, and a to-do or agent task you start from a note carries the meeting's sources with it as attachments. The Companion can investigate a note by reading only those attached sources and your Basil records, and it never changes them. The **Research automatically** switch lets it start that research when a topic calls for it, and you can turn it off. A standing watch tells the Companion to surface something whenever a topic comes up, for example "when pricing comes up, give me last quarter's numbers."

A note can become a To-Do or an agent task. **Make to-do** and **Hand to agent** on a note act as your approval and create the item at once. The Companion can also offer a to-do or agent task as a card when someone in the meeting commits to or asks for a concrete follow-up. The card shows the full instruction and nothing starts until you approve it. Only a watch you created can start an action by itself, and only when you enable **Let my watches start actions without asking**.

The Companion records every time it checked the conversation, including the times it stayed quiet. The pane shows how many times it checked and how often it spoke, **Show what it considered** lists each check with what the Companion weighed and why a possible note was kept or dropped, and **Why this?** on a note explains the reasoning for it. A quiet Companion is therefore distinguishable from a broken one.

**Audit so far** reads the transcript, what the Companion said, and what it considered, then lists moments where a note, to-do, agent task, or research would have helped and nothing did. Each finding has **Show in transcript**, **Investigate**, and **Make to-do** actions and a **Good catch** or **Not needed** mark. When a meeting ends after enough Companion activity, an audit runs by itself. A saved meeting reopens with its notes, considered record, and audit, and you can still investigate a note, make a to-do, or run an audit there.

Detach the Companion to open it in its own window. While that window is open, the Notetaker shows a thin rail with a button that brings the window to the front, and the column returns when you close the window. The Companion is stored with the meeting under `~/.basil/meetings/`, and it uses the same reasoning model path as Notetaker analysis, so a provider-backed model receives the transcript, notes, and attached-source text it needs. Read [Privacy and data flow](privacy-and-data-flow.md) before choosing that path.

### Meeting/Call Detection

Configure Meeting/Call Detection in Settings → Notetaker, then start or stop the current monitor from the Basil menu unless the separate start-at-launch preference is enabled. Detection looks for non-excluded macOS processes that are concurrently using audio input and output. It can operate in `prompt` mode, which opens a confirmation panel, or `auto_start` mode, which begins the configured detected-meeting flow.

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

Colors carry the same meaning throughout Basil. Amber means it is your turn, such as a question, approval, checkpoint, or missing permission. Red means an error. Gray means paused. Purple means Basil is working. A half-filled green circle means a task finished only part of its work. Teal means a notice, such as a lost connection or a heads-up. Teal is fixed and does not follow your appearance colors; the other colors follow them.

For step-by-step configuration guidance, read [Configuration](configuration.md). For model and data boundaries, read [Privacy and data flow](privacy-and-data-flow.md).
