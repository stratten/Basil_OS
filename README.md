# Basil

Basil is a local-first macOS AI assistant. It combines a native Swift client, a local Python/FastAPI service, and focused WebKit application surfaces so that assistance, capture, transcription, meetings, automation, and personal context can live in one desktop workflow. You can use downloaded local models, models reached through your own provider key, custom model endpoints, or Basil Cloud where available.

<p align="center">
  <a href="https://github.com/stratten/Basil_OS/releases/latest/download/Basil.dmg"><img src="docs/download.svg" alt="Download Basil for Mac" width="236" height="60" /></a>
</p>

<p align="center">
  <a href="https://github.com/stratten/Basil_OS/releases">All releases</a> · <a href="docs/verifying-builds.md">Verify a build</a>
</p>

## What Basil does

### Workspaces, conversations, and agent work

The Basil Board is the main workspace for beginning an inquiry, reopening work, viewing meeting state, and moving among conversations, Paprika tasks, and todos. Conversations retain threaded work around an ongoing subject. **Dill (Quick Assist)** (default hotkey ⌥⌥) answers each request in a single model turn and provides a focused text-or-voice surface with saved outputs, refinement, and copy controls.

<p align="center">
  <img width="2240" alt="The Basil Board: a prompt box headed What can I do for you, with a model picker and recent work listed below" src="https://github.com/user-attachments/assets/77971b3d-1637-4ddc-a142-a2ab7c785feb" />
</p>

**Paprika (Agent)** (default hotkey ⌥Space) runs goal-oriented, multi-step tasks that can start from text, files, images, captured audio, or screen context. A task can show progress and intermediate activity, present results and local artifact previews, accept revisions, and request approval before taking an action. Tasks can be scheduled, reviewed, paused, or canceled when their state supports it. The todo workspace tracks work through inbox, open, in-progress, review, and completed views, with details, ordering, dates, and status for agent-backed work.

<p align="center">
  <img width="840" alt="A Paprika agent task with follow-ups, a progress timeline on the right, and a verified result" src="https://github.com/user-attachments/assets/02f7c237-254c-4a6d-bbc8-b9bfc0d35edd" />
</p>


### Capture, OCR, and transcription

Use the menu bar, the Board, or a configurable hotkey to capture screen or window content for OCR, visual analysis, and context-assisted work. The capture result remains subject to the selected model path: a local model processes it on the Mac, while a provider-backed model may receive the content required for the request.

<p align="center">
  <img width="284" alt="Basil's floating widget, a small green orb on a dark blue tile" src="https://github.com/user-attachments/assets/0e354643-3d75-456f-9ada-8966e59a2138" />
</p>

(Yes, it does look like a dishwasher tablet, now that you mention it)


The transcription widget records live microphone audio, and the menu also offers transcription of a user-selected local audio file. Transcription history supports retrieval, review, copying, playback when recorded audio exists, and retranscription with an available model. Settings control the model, paste behavior, post-completion behavior, history, and text-replacement rules applied before insertion. Hotkeys are configurable; examples in this documentation are not promises of a fixed binding.

### Notetaker and Meeting/Call Detection

Open **Notetaker** from the Basil menu to create a manual recording of a meeting or call. Before recording, you can set the meeting name, purpose, participants, and available microphone or system-audio source. During a meeting, the Notetaker exposes source meters, recording state, and a live transcript. Afterward, it retains meeting metadata and history, supports searching and reopening stored meetings, and can improve a transcript, add speaker labels, or run analysis such as summaries, action items, decisions, questions and answers, sentiment, or a custom instruction.

<p align="center">
  <img width="1910" alt="Notetaker showing a past meeting with a transcript split by microphone and system audio, and transcript tools below" src="https://github.com/user-attachments/assets/b1bb1a23-7d5b-4a55-85e7-de09b2d0b579" />
</p>


<p align="center">
  <img width="600" alt="Meeting Analysis listing To-Do candidates that Basil identified, each with Start now, Add to To-Dos, Edit, and Dismiss" src="https://github.com/user-attachments/assets/a4627980-b7cf-4850-96bc-dd5d7bb18552" />
</p>


The optional **Companion** sits beside the live transcript and can offer notes, answer questions about the meeting, watch for topics you name, and research your attached files. It keeps a record of what it considered, turns a note into a To-Do or agent task only when you approve it, and can audit a meeting afterward for moments it should have helped. See [Capabilities](docs/capabilities.md#notetaker-companion).

Meeting/Call Detection is a separate opt-in monitor. It observes non-excluded macOS processes that are concurrently using input and output audio, then either prompts or starts the configured detected-meeting flow. Passive detection does not create an audio tap or record audio. Calendar access can enrich a detection, require an active calendar match, or present a join prompt for a joinable event. Only one detected-meeting launch or recording can be active: after Basil begins preparing or recording a meeting, additional detections cannot open another panel.


### Personal context and proactive assistance

Profile, writing examples, and Personal Context let you control information that can tailor drafting and reasoning. Activity Capture can create local records on a configured schedule, with source, exclusion, retention, cleanup, and processing controls. Memories and personal-context workflows organize selected information into durable context.

Skills provide reusable guidance for agent work, and the Skills settings surface includes reconciliation tools for reviewing and aligning that material. Setup and onboarding guide initial preferences, permissions, models, and connections. Proactive Suggestions can offer configured assistance based on its runtime settings. None of these capabilities silently grant permission, connect an account, or override an approval gate.

### Automation and connected services

Basil can use browser automation, desktop automation, Apple Events, commands, and connected services when you configure the corresponding capability and approve the action. Connections support Model Context Protocol (MCP) services and Agent Client Protocol (ACP) provider profiles. The optional voice listener can initiate configured voice-driven workflows, but it is only an input method; any resulting automation remains subject to its normal permission and approval controls.

Automation can affect local and external systems. A request to an agent is not authorization to send a message, modify a record, run a command, or perform another side effect. Review the target, requested capability, and approval prompt before allowing an action.

### Models, settings, and account choices

Settings are grouped into General, Personalization, Capabilities, and System. They cover Home, Hotkeys, Profile, Personal Context, Writing Examples, Models, Automation & Agents, Transcription, Notetaker, Capture, Connections, Permissions, Account, and Appearance & Format.

Choose model paths independently for supported reasoning and transcription work: downloaded local models, direct provider/API models using your key, custom models, or Basil Cloud. Provider enablement is distinct from choosing to use your own API key. Some settings make a capability available without starting its background runtime; Meeting/Call Detection, for example, must be started from its dedicated control unless its separate start-at-launch preference applies.

<p align="center">
  <img width="1540" alt="Settings Home showing setup status, default models, launch preferences, and active features" src="https://github.com/user-attachments/assets/731c1c38-3b3d-4db5-847a-b7b8c1c5ec90" />
</p>


## Quick start for development

Basil currently supports macOS. Install Xcode or the Swift toolchain, Python 3.11, [Poetry](https://python-poetry.org/), Node.js with npm, and Homebrew. The backend and packaged application require LLVM, Tesseract, TBB, libsndfile, PortAudio, and coreutils; packaging also requires CMake and Homebrew's Bash.

```bash
git clone git@github.com:stratten/Basil_OS.git basil
cd basil
brew install bash cmake llvm tesseract tbb libsndfile portaudio coreutils
export LLVM_CONFIG=/opt/homebrew/opt/llvm/bin/llvm-config
poetry install
./dev.sh
```

`./dev.sh` builds the pinned LGPL FFmpeg dependency when necessary, refreshes the embedded web assets, starts the local backend, builds the native client, and launches the development app. It deliberately terminates existing Basil development backend processes and development-client instances before it starts. Do not run it over an active development session that you or another workflow needs to keep. Read [Getting started](docs/getting-started.md) for first-launch permissions, Apple Silicon LLVM guidance, and the complete local setup flow.

## Privacy, providers, and permissions

Local-model inference remains on your Mac. Direct-provider models send the selected request content to the provider you configure, and custom endpoints receive the content needed for their configured request. Basil Cloud is optional rather than required for local or bring-your-own-key operation. Provider credentials may be supplied through environment variables or Basil's local provider-key settings; no credentials are included in this repository.

Capabilities that record microphone audio, inspect screen or window content, use Calendar or Contacts, watch global hotkeys, automate desktop applications, or contact an external service require the corresponding macOS permission, user approval, account, model, or connection. Meeting recordings, transcriptions, conversations, tasks, captures, models, and configuration can contain private information. Review [Privacy and data flow](docs/privacy-and-data-flow.md) before choosing a provider, granting access, connecting a service, or deleting local data.

## Documentation

- [Getting started](docs/getting-started.md) explains prerequisites, local setup, first launch, and permission prompts.
- [Capabilities](docs/capabilities.md) is the detailed user-facing capability catalog, including entry points, persistence, dependencies, and limitations.
- [Configuration](docs/configuration.md) explains Settings, model paths, API keys, Basil Cloud, connections, permissions, and runtime controls.
- [Privacy and data flow](docs/privacy-and-data-flow.md) describes local storage, permission boundaries, provider data handling, connected services, and meeting data.
- [Development](docs/development.md) documents the architecture, canonical web-asset builders, validation commands, and release boundaries.
- [Repository layout](docs/repository-layout.md) and [generated files](docs/generated-files.md) explain source roots, generated artifacts, and resource staging.
- [Verifying repository builds](docs/verifying-builds.md) explains how to download the latest signed build of `main` and confirm which commit it was built from.

## Development and release

The canonical source surfaces are `client/` for the native macOS application, `backend/` for the FastAPI service, and `web-components/` for embedded React/Vite renderers. Build the shipped WebKit resources with the canonical scripts under `scripts/`; staged bundles and local runtime data are not source files.

Run the narrowest relevant validation for a change, such as `poetry run pytest`, `swift test --package-path client`, `swift build --package-path client`, or a package-local `npm test` and `npm run build`. Use [Development](docs/development.md) for the source boundaries, builders, and validation workflow.

Community builds use `build/scripts/build_app.sh --ad-hoc`. Signing, notarization, update feeds, artifact upload, and DMG publication require release-owner credentials and can change external systems; they are not routine contributor operations.

Every push to `main` that changes more than the README also produces a signed, notarized build with a GitHub build-provenance attestation. The release owner promotes a chosen build by hand, either to the `main-latest` pre-release or to a numbered stable release; stable releases update themselves through Sparkle from this repository's `update-feed` release. [Verifying repository builds](docs/verifying-builds.md) explains how to confirm that a download matches the code in this repository.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Use [SUPPORT.md](SUPPORT.md) for reproducible bugs, installation problems, and feature requests. Do not report vulnerabilities publicly; follow [SECURITY.md](SECURITY.md).

## License

Copyright 2026 Stratten Waldt. Basil is licensed under Apache-2.0; see [LICENSE](LICENSE), and [NOTICE](NOTICE) for vendored third-party code. The Basil name and official-distribution identity are governed separately by the [Trademark Policy](TRADEMARK.md).
