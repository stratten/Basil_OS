# Changelog

User-facing changes to Basil, newest first. Each website release has a `## X.Y.Z` section whose bullets become that release's in-app update notes. Changes on `main` that have not shipped in a website release are listed under `## Unreleased`, and those bullets also appear in the notes of the rolling `main-latest` repository build.

Write one bullet per line, starting with `- `, in plain language for people using the app. Do not use `<` or `&`, because the update notes are rendered as HTML. When cutting a website release, rename `## Unreleased` to the new version and add a fresh, empty `## Unreleased` above it. Entries begin with 1.1.5.

## Unreleased

- The Meeting Assistant is now called Notetaker, in the Basil menu, Basil Board, and Settings, and Meeting Detection is now Meeting/Call Detection
- A paused Notetaker recording now shows amber instead of the red used for a live microphone, and its buttons read simply Start, Resume, End, and Analyze
- Hover hints now look the same throughout Basil, appear after a short pause, and show up only where they add something, such as a full file name that is cut off
- When Basil asks you a question during a task, the question now survives quitting or restarting Basil for up to 7 days, and answering it continues the task
- After you answer a question Basil asked mid-task, the task builds on the work it had already done instead of repeating it
- Longer agent tasks that use Claude are faster and cheaper, because Basil reuses the unchanged part of each request
- Basil now cleans up saved agent task history it can no longer use, which could grow past a gigabyte, and saves less of it per task
- Claude Sonnet 5.5 and GPT-6.1 Sol are now available, and Claude Sonnet 5.5 is the recommended Claude model; the retired Claude Opus 4 and Claude Sonnet 4 are removed, and several Claude, Gemini, and GPT-4.1 models can now give longer answers

## 1.1.7

- Your own provider API keys are now stored in the macOS Keychain instead of a plain-text file. Keys entered in earlier versions are not carried over, so if you use your own OpenAI, Anthropic, or other provider keys, re-enter them in Settings after updating. The old file at ~/.basil/config/api_keys.json is no longer used and can be deleted.
- New GPT-6 models are available: GPT-6 Astra, GPT-6 Sol, and GPT-6 Luna
- Choose when Basil pastes a finished response: Always, Never, or Let Basil decide, which pastes drafts, replies, and rewrites while keeping explanations, answers, and research in the widget
- Save your own appearance themes and switch between them from Appearance settings
- New "Metallic (background only)" surface finish puts a brushed-metal sheen on window backgrounds while messages, cards, and inputs stay solid
- Saved writing examples can now be edited, including their content, context, and recipient
- The Power User Guide has been redesigned, with new icons and a "Dill or Paprika?" section that explains which one to use
- Agent Task titles, sidebars, and history previews now show clean text instead of raw Markdown symbols
- Refreshed menu bar icons
- Stability and polish — ongoing reliability, performance, and quality improvements throughout

## 1.1.6

- Fixed Setup Assistant startup: model-download guidance now loads correctly instead of showing a template-variable error.

## 1.1.5

- New appearance customization — choose between Flat and Metal surface finishes for your color presets, giving you finer control over how the app looks
- Refreshed the "Precursor" color preset (previously "Precursor Metal") with revised tones that better capture the intended palette instead of leaning too heavily into darker shades
- Steadier recordings — Basil no longer swaps out your active transcription model while you're mid-recording, preventing dropped audio during longer capture sessions
- Onboarding now remembers your preferred interaction style instead of resetting it on the next run
- Vision-capable models you've configured are now properly enabled and available for use
- Agent Task actions — including skill-related actions — now show helpful tooltips explaining what each one does
- Meeting detection can now be configured to launch automatically at startup, and stale or superseded "join this meeting" prompts are dismissed automatically instead of lingering
- Agent Tasks waiting on your input or access are now called out distinctly and can be safely canceled from that state
- Saffron Setup Studio can now be resized freely without its contents getting clipped
- A new unified workflow lets you investigate your local activity, conversation, and related history data in one place
- Meeting detection now shows which calendar a detected meeting came from
- The To-Do workspace has been substantially refined: independent detail viewing, selected-task chips, a view-all option, due dates, direct-click primary detail, new lifecycle and edit controls, a collapsible layout, file/path references, and handoff context from the source Agent Task
- Cmd-Shift-V now pastes as plain, unformatted text across shared rich-text composer surfaces
- You can now navigate directly to a skill's source Agent Task, and we fixed issues with skill deletion, duplicate creation, and sluggish skill-list behavior
- Paprika can now be configured to automatically expand when a delegated task completes
- Activity Capture's progress lifecycle is more reliable, active processing now refreshes correctly when you reopen the tab, and near-duplicate captures are reduced
- Stability and polish — ongoing reliability, performance, and quality improvements throughout
