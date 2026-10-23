# Changelog

User-facing changes to Basil, newest first. Each website release has a `## X.Y.Z` section whose bullets become that release's in-app update notes. Changes on `main` that have not shipped in a website release are listed under `## Unreleased`, and those bullets also appear in the notes of the rolling `main-latest` repository build.

Write one bullet per line, starting with `- `, in plain language for people using the app. Do not use `<` or `&`, because the update notes are rendered as HTML. When cutting a website release, rename `## Unreleased` to the new version and add a fresh, empty `## Unreleased` above it. Version 1.0.0 is the first public release, so its section summarizes what Basil does as a whole; the changes recorded during private development are kept in [docs/pre-release-history.md](docs/pre-release-history.md).

## Unreleased

## 1.0.0

- Basil is a local-first AI assistant for your Mac: run a model on your Mac, or use your own Anthropic, OpenAI, or Google key, any OpenAI-compatible endpoint, or Basil Cloud where it is available, and no account is needed for the first two
- The Basil Board is your main workspace: a single Home input sends each request where it belongs, Chats keeps ongoing conversations, Agents holds your tasks, and To-Dos tracks work that takes more than one sitting
- Dill answers a question or drafts and rewrites text in a single step from a hotkey, by typing or by voice, and keeps your saved outputs so you can refine, edit, copy, or save one as a writing example
- Paprika is the agent: it works through multi-step tasks from a hotkey, shows its progress, uses your files, browser, and desktop, asks before anything consequential, and can be scheduled, paused, resumed, and followed up with notes
- Capture any screen or window for text recognition and visual questions, dictate with live transcription, or transcribe an audio file, with a history you can replay and retranscribe and replacement rules applied before text is pasted
- Notetaker records your meetings and calls with a live transcript, then improves the transcript, labels speakers, and writes summaries, decisions, and action items, and Meeting/Call Detection can prompt you or start a recording for you
- The Companion sits beside a live transcript with notes, answers, topics to watch for, and research in the folders and files you attach, which you can add even after the meeting ends, and a to-do or agent task it suggests starts only when you approve it
- Teach Basil about you with a profile, writing examples, memories, and skills, and connect other tools through MCP and ACP, with approval controls you set for every command, connection, and external action
- Your history, recordings, transcripts, and settings are files on your Mac, your own API keys are kept in the macOS Keychain, and Basil is open source under Apache-2.0
- Make it yours with built-in color palettes and your own saved themes, and updates arrive in the app, signed and checked before they install
