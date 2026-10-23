# Improvements before the first public release

Basil's first public release is 1.0.0, and its [changelog](../CHANGELOG.md) describes what the application does as a whole. This file keeps the running list of changes that were recorded while Basil was in private development, when internal builds carried the version numbers 1.1.5 through 1.1.7 and the changes after 1.1.7 were still unreleased. It is a historical record, not release notes: nothing here is read by the build, and new changes go in the changelog from 1.0.0 onward.

## Most recent changes before 1.0.0

- You can now add or remove Companion sources on a meeting that has already ended, so a repository you forgot to attach during the call can still ground its open questions and proposed to-dos
- A to-do or agent task you start from a Companion note now carries the meeting's attached sources with it as attachments, so the work starts with the same context the Companion was using
- Everywhere you attach files or folders, including a to-do's detail view, now uses one Attachments / References area with the same Add button, drag and drop highlight sized to that area, and file chips
- A scheduled run is now drawn exactly like any other task run, in the scheduled runs panel and in a schedule's Run History: the same labels and dots, with a partial result shown as the half green mark instead of a red failure dot, a result still being checked shown as Verifying the outcome instead of a verdict, and a run that finishes with a partial result is now recorded as completed with the partial note instead of failed
- You can now archive a finished task: swipe its row in the sidebar and choose Archive to take it off the Tasks list, open the Archived view from the sidebar header to find it again, and choose Unarchive there to bring it back
- A schedule can now be pinned to its own reasoning model, shown as Default model until you choose one, and a run whose pinned model is no longer installed or enabled uses the default model and says so in the schedule's run history
- When Basil asks to approve a command, the approval now shows What this does in the agent's own words, or warns you if the agent gave no explanation, along with the agent's recommendation to remember the choice or ask each time, and Remember is no longer offered for kinds of command that can never be remembered
- While Notetaker is recording, a small advice chip now appears when your Mac is running hot, low on memory, or working at its limit, or when transcription falls behind or the Companion slows down, with what to do about it
- Schedules in the sidebar now show whether they are still running: a solid green dot means active and a hollow ring means inactive, and an inactive schedule says Inactive in its second line
- Deleting a schedule from the sidebar now asks Delete this schedule? with Cancel and Delete buttons first, like every other sidebar item, instead of removing it immediately
- Skip on a request for input now stays skipped when you leave a task and come back, and leaves a compact Input required card with an Answer now button so you can still answer it
- The Stop button in the header now also appears while a task is waiting for your input, matching the cancel option in the sidebar
- Choosing See work so far on a request for input now collapses the question into a compact card at the bottom of the window instead of a large panel, so the work stays visible, and its Answer now button reopens the full question with everything you had entered
- The scheduled runs panel no longer opens blank: Basil now waits for the panel to finish starting before sending it its data, which was previously sent too early and lost, so the running tasks, their theme and their text colors now appear
- Input and control outlines inside every window are soft again: they are drawn from your theme's secondary color at 20% instead of arriving fully opaque from the app
- Dividers and header borders inside every window are soft again: they are now drawn from your theme's secondary color at a light strength instead of the system separator color, which became much heavier in macOS 27
- The scheduled runs panel no longer stays open as an empty box: it retries loading the running tasks and hides itself when there is nothing to show, finished runs stay readable for 15 seconds (failed ones for 60), a run that is waiting for your approval now says so, and its text stays readable on dark themes
- Agent tasks that are asked to keep checking on something every so often, such as every 30 minutes, now schedule each check as a follow-up inside the same task instead of creating a separate scheduled task, so the checks stay in one continuous chain with their earlier context
- A scheduled run now does the work its schedule describes instead of creating another schedule: the schedule text no longer carries its own timing wording, and a scheduled run is refused if it tries to create a schedule
- Companion cards no longer overflow their width: the header wraps, the Researched label sits below the Show in transcript button, and the dismiss button stays pinned to the top right corner
- The Meeting Companion now finds answers in attached project folders much more reliably: searches match a question's separate words instead of requiring the exact phrase, results no longer fill up with the opening lines of unrelated files, and research can open a long file and jump straight to the passages that matter
- Builds downloaded from GitHub now update themselves through Sparkle from the repository's own update feed, the same way the website build does, and every update is checked against a dedicated signing key
- Home in the Basil Board is now a single centered input that sends your request where it belongs: questions open in Chats with the message already sent, and tasks open in Agents, or in the task window if it is already open
- After Home routes a request, a short notice says where it went and lets you correct it with one click, such as Send as agent task instead or Answer in a chat instead
- Home now lists your last few requests as simple links that reopen the chat or task, instead of a history sidebar and transcript
- The Meeting Assistant is now called Notetaker, in the Basil menu, Basil Board, and Settings, and Meeting Detection is now Meeting/Call Detection
- Conversations that started from Home can now be deleted; before, deleting one failed and Chats reported it as not found
- Swiping a Chats row to reveal Delete now slides the row's hover buttons along with it, and a task that completed with warnings now shows as a partial result in the run status card as well as in the sidebar
- In Notetaker analysis, a suggested action's proposed task can no longer be opened for editing after it has been added to To-Dos or started, since there was nothing to save it to
- The Description and Notes fields in a To-Do now keep a faint outline when you are not editing them, so they read as editable areas
- The Participants box in Notetaker now resizes to fit its names when the window or a side pane changes width, instead of staying tall or clipping names
- Renaming a meeting, or changing its purpose or participants, after it was analyzed now updates what its analysis window shows, including after you close and reopen it
- A paused Notetaker recording now shows gray instead of the red used for a live microphone, and its buttons read simply Start, Resume, End, and Analyze
- Hover hints now look the same throughout Basil, appear after a short pause, and show up only where they add something, such as a full file name that is cut off
- When Basil asks you a question during a task, the question now survives quitting or restarting Basil for up to 7 days, and answering it continues the task
- After you answer a question Basil asked mid-task, the task builds on the work it had already done instead of repeating it
- Longer agent tasks that use Claude are faster and cheaper, because Basil reuses the unchanged part of each request
- Agent tasks no longer restart part of their work when they need an additional set of tools
- Follow-up requests now continue the actual conversation, including the files Basil read and the tools it ran, so a follow-up no longer depends on a short summary of the previous turn; this also works when you switch models between turns and for quick answers that don't need tools
- Custom models have a new Server Type setting: choose Ollama and Basil sends the model's context window to Ollama when it loads the model, instead of Ollama's smaller default
- Long tasks on local models now shorten older material before the context fills up, and if a task still needs more context than the model holds, Basil stops and tells you which model ran out, how large its context window is, about how much the task needed, and how to fix it
- Basil now cleans up saved agent task history it can no longer use, which could grow past a gigabyte, and saves less of it per task
- Claude Sonnet 5.5 and GPT-6.1 Sol are now available, and Claude Sonnet 5.5 is the recommended Claude model; the retired Claude Opus 4 and Claude Sonnet 4 are removed, and several Claude, Gemini, and GPT-4.1 models can now give longer answers
- You can now pause a running agent task and resume it later, even after restarting Basil, and you can send Basil a note while it works, which it reads before its next step
- Stop now also stops a task that was continuing after you answered a question, and a stopped task no longer keeps pulsing in the sidebar or the run map
- The run map no longer keeps showing a question as waiting after you have answered it, and a question waiting on you now shows an amber "Your turn" marker instead of a plain pulse
- Basil's reasoning now stays closed until you open it; once open it follows the newest step while Basil thinks, and it folds closed when the task finishes
- While a task runs, one thin status card above the message box shows what it is doing, such as Working, Verifying the outcome, Paused, or Needs attention, and a stopped task now shows a neutral Canceled card with Run again instead of looking like a failure
- You can attach files or folders to a note you send a running task or to the note you add when you resume a paused task
- Follow-up questions start on the model used for the previous turn
- Browser tasks now use one dedicated browser window per task, including its follow-ups, so Basil no longer loses track of which tab it was working in
- Basil's bundled networking, image, PDF, and security libraries are updated to versions that fix publicly reported security advisories, and PDF text is now read with the maintained pypdf library
- Links in Notetaker analyses, Companion cards, and Companion chat answers now open in your default browser or mail app when you click them, where before the click did nothing
- When a small local model puts a whole command line in the command field of a shell step, such as a command with a pipe, Basil now runs it the way the model meant instead of failing, and a command that keeps failing the same way now tells the model exactly what was wrong and stops repeating sooner
- The notice that says where Home sent your request now sits in the top bar, so it is no longer hidden behind the task view
- To-Do due dates now save the date you typed instead of a partial year, and the detail pane shows the same day as the list instead of the day before
- The confirmation that appears when you delete a To-Do now follows your appearance colors and has a properly styled Delete permanently button
- Models that their providers are shutting down are removed: GPT-4o, GPT-4o Mini, GPT-4.1, and GPT-4.1 Mini (January 14, 2027), o1, o3 Mini, o4 Mini, GPT-4.1 Nano, and GPT-4 Turbo (October 23, 2026), Claude Sonnet 4.5 (November 30, 2026), Gemini 2.5 Pro, Gemini 2.5 Flash, and Gemini 3 Flash, and GPT-5, GPT-5 Mini, GPT-5 Nano, GPT-5.1, and GPT-5.4 Nano (December 11, 2026 and April 1, 2027); a saved choice of any of these except the GPT-5 family moves to the provider's replacement (GPT-5.4 Mini, GPT-6 Luna, GPT-5.6 Sol, Terra, or Luna, Claude Sonnet 5.5, Gemini 3.1 Pro Preview, or Gemini 3.8 Flash) the next time Basil starts, GPT-5.6 Terra is now the recommended OpenAI model, Claude Haiku 5.5 is now available, and ambient suggestions now default to GPT-5.4 Mini
- When Basil continues a task on its own, such as after its outcome check finds a gap, that turn is now labeled Agent revision instead of Follow-up, and agent revisions and your own follow-ups are numbered separately
- Each turn of a task now shows only its own source, so a follow-up no longer repeats the Conversation or To-Do chip of the turn that started the task
- Error, warning, and highlight colors in the Basil Board, agent task results, Settings, and the small panels now follow your appearance colors instead of fixed ones, which fixes hard-to-read text in dark appearances
- Colors now mean one thing each across Basil: amber appears only when it is your turn, red is only for errors, a paused task or recording is gray, a task that finished only part of its work shows a half-filled green circle, and notices such as a lost connection or a heads-up are teal
- Playing back a saved dictation in Settings now shows a progress bar with the elapsed and total time, and you can click or use the arrow keys on the bar to jump to any point in the recording
- The Notetaker Companion now keeps a record of every time it checked the conversation, including the times it stayed quiet: the pane shows how many times it checked and how often it spoke, a switch shows each check with what the Companion weighed, and every note has a Why this? explanation
- Live transcript words no longer run together while a local model is transcribing, which also gives the Companion cleaner text to read and search with
- Companion notes now have Make to-do and Hand to agent buttons that act on the note when you click them, and the Companion can also offer a to-do or agent task as a card when someone in the meeting commits to a follow-up; nothing starts until you approve it
- The Companion can now research on its own when a topic calls for it, with a Research automatically switch to turn that off, and saved meetings now keep their Investigate buttons so you can research a note after the meeting ends
- The Companion can now audit a meeting: Audit so far lists the moments where a note, to-do, agent task, or research would have helped and nothing did, with Show in transcript, Investigate, and Make to-do actions and Good catch and Not needed marks; an audit also runs by itself when a meeting with enough Companion activity ends
- While the Companion is open in its own window, the Notetaker narrows the Companion column to a thin rail with a button that brings that window to the front, and the column returns when the window closes

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
