// Setup-agent system prompts that the SetupAssistantApp injects at
// specific moments: stage handoffs (intro -> orientation -> conversation),
// re-engagement turns after a launched task/session lands a structured
// observation, optional email-metadata enrichment, and finalize wrap-up.
//
// Kept colocated as a single module so copy edits land in one place — the
// agent's tone hinges on these strings being precisely worded.

export const SETUP_FINALIZE_PROMPT =
  'The user clicked Done with setup. Form a wrap-up now based on the conversation so far and the discovery facts you already have. Call propose_wrap_up exactly once.'

export const SETUP_CONVERSATION_START_PROMPT =
  'The user clicked Continue with setup after reviewing the orientation notes. Now start the setup conversation. Briefly explain the most useful paths forward based on the discovery facts and orientation notes, and define Dill and Paprika before suggesting either by name.'

export const EMAIL_METADATA_CONTEXT_PROMPT =
  'The user asked to try Dill with email. I collected approved local sent-email metadata for context. Use those facts to propose a realistic email-writing setup path. Do not claim there is a selected or incoming email thread unless the user said one is selected.'

export const AGENT_TASK_PROGRESS_PROMPT =
  '[system observation] A launched Paprika task posted a non-boilerplate progress update. The full structured observation is in execution_outcomes. If the update is worth telling the user, say so in a sentence; otherwise emit a single narrate_progress and stay quiet.'

export const AGENT_TASK_TERMINAL_PROMPT =
  '[system observation] A launched Paprika task reached a terminal state. The full structured observation is in execution_outcomes. Narrate the outcome in first person, evaluate whether it succeeded, and propose the next reasonable step. Also check whether this terminal completes an active agenda item (commonly intro_paprika after a Paprika demo) — if it does, call mark_agenda_item(id, "completed", completion_basis=...) in the same turn and orient the user toward one or two specific remaining agenda items by name (e.g. "That covers the Paprika intro — want to walk through the menu bar item next, or stay with Paprika?") rather than proposing a generic next step.'

export const ASSISTANT_SESSION_TERMINAL_PROMPT =
  '[system observation] A launched Dill assistant session reached a terminal state. The full structured observation is in execution_outcomes (kind: assistant_session_terminal). The draft itself is already on screen for the user in two places: an inline draft card sits in the conversation just above the reply you are about to send, and the same draft is open in the Dill widget where the user can edit, save as a writing sample, or discard it. Read the draft from result_text, narrate the outcome in first person (briefly summarize what Dill came up with and what makes the approach work for this email — do not re-paste the draft), and propose the next reasonable step. When pointing the user at the editable copy, refer to it as the Dill widget rather than "above" — the inline card in the conversation is read-only and the widget is where edits land. Also check whether this Dill terminal completes an active agenda item (commonly intro_dill after a Dill demo). If it does, decide between marking it complete unilaterally via mark_agenda_item("intro_dill", "completed", completion_basis=...) when the draft is clearly strong and the user has been engaged, OR calling request_agenda_item_confirmation("intro_dill", prompt=...) when you want to give the user an explicit "show me one more" off-ramp before flipping the sidebar pill. After any agenda update, orient the user toward one or two specific remaining agenda items by name rather than proposing a generic next step.'

export const AGENDA_CONFIRMATION_RESOLVED_PROMPT =
  '[system observation] The user just responded to an inline agenda-confirmation card. The full structured observation is in execution_outcomes (kind: agenda_confirmation_resolved) with agenda_item_id and resolution. On resolution="confirmed", call mark_agenda_item(agenda_item_id, "completed", completion_basis="user confirmed via agenda confirmation card") and orient toward one or two specific remaining agenda items by name. On resolution="not_quite", leave the item active (no mark) and ask the user what specifically still isn\'t clear before offering to walk through whichever piece they name. On resolution="skipped", call mark_agenda_item(agenda_item_id, "skipped", completion_basis="user skipped via agenda confirmation card") and pick a natural next move from the remaining agenda. Do not silently move on without acknowledging the resolution.'
