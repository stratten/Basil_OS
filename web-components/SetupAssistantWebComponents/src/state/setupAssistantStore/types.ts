import type {
  SetupAgentEvent,
  SetupAgentModelAccess,
  SetupAppearanceChangeSummary,
  SetupArtifact,
  SetupConsentReceipt,
  SetupDiscoveryFact,
  SetupInlineEmailContext,
  SetupInlineVisual,
  SetupOrientationObservation,
  SetupSuggestionChip,
  SetupToolApprovalState,
  SetupWrapUpProposal,
} from '@/types'

export type SetupAgentTaskOutcomeKind = 'agent_task_progress' | 'agent_task_terminal'

export interface SetupAgentTaskOutcome {
  agent_task_id: string
  kind: SetupAgentTaskOutcomeKind
  status: string
  current_step?: string
  result_message?: string
  error_message?: string
}

export interface SetupTrackedAgentTask {
  agentTaskId: string
  registeredAt: number
  lastStatus: string | null
  lastResultMessage: string | null
  lastObservationAt: number
  isTerminal: boolean
}

export interface SetupAgentTaskObservationTurnRequest {
  agentTaskId: string
  outcome: SetupAgentTaskOutcome
  isTerminal: boolean
}

// Setup-launched Dill (launch_assistant_session) currently emits only a
// terminal observation — see the AssistantSessionWindowController
// observation seam for the rationale (Dill drafts complete in seconds and
// the in-flight streaming output is already visible in the Dill widget).
// The 'assistant_session_terminal' literal mirrors the
// 'agent_task_terminal' shape so the setup agent's reaction handler can
// treat both observation flows symmetrically as execution_outcomes
// entries.
export type SetupAssistantSessionOutcomeKind = 'assistant_session_terminal'

export interface SetupAssistantSessionOutcome {
  assistant_session_id: string
  kind: SetupAssistantSessionOutcomeKind
  status: string
  result_text?: string
  error_message?: string
}

export interface SetupTrackedAssistantSession {
  assistantSessionId: string
  registeredAt: number
  lastStatus: string | null
  lastResultText: string | null
  lastObservationAt: number
  isTerminal: boolean
}

export interface SetupAssistantSessionObservationTurnRequest {
  assistantSessionId: string
  outcome: SetupAssistantSessionOutcome
  isTerminal: boolean
}

// Inline conversation primitive for a Dill draft that finished streaming
// in the Dill widget. Inserted into the message timeline when the
// setup-launched assistant session reaches a terminal state, so the
// draft itself has a positional anchor in the conversation rather than
// living only inside the separate Dill widget window. Carries its own
// copy of the result text so it's stable even after the corresponding
// `trackedAssistantSessions` entry has been cleared.
export interface SetupInlineDillDraft {
  assistantSessionId: string
  status: 'completed' | 'failed'
  resultText?: string
  errorMessage?: string
  applicationName?: string
  createdAt: string
}

// Session agenda — the visible spine of the setup session. The agent
// proposes the agenda once (replacing any prior state) and edits per-item
// status via incremental marks; the frontend renders it as a sticky
// sidebar so the user has a continuous sense of "where we are in the
// bigger arc." Source distinguishes catalog-seeded items from agent-
// authored additions so the UI can subtly mark provenance (and future
// telemetry can measure catalog coverage). Completion basis is captured
// for the session transcript; not rendered to the user today.
export type SetupSessionAgendaItemKind = 'action' | 'demo' | 'literacy' | 'conversational'

export type SetupSessionAgendaItemStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'skipped'
  | 'deferred'

export type SetupSessionAgendaItemSource = 'catalog' | 'agent'

export interface SetupSessionAgendaItem {
  id: string
  title: string
  intent: string
  kind: SetupSessionAgendaItemKind
  source: SetupSessionAgendaItemSource
  status: SetupSessionAgendaItemStatus
  completionBasis?: string
}

// Inline "did this land?" confirmation card the agent surfaces after a
// literacy walkthrough or capability demo where completion isn't
// observable from any side-effect. The card renders chronologically in
// the conversation with Yes / Not quite / Skip affordances; the
// resolution is dispatched back to the agent as an execution outcome
// so it can react in the next turn. `resolution` is undefined while
// the card is awaiting the user; once the user clicks one of the
// affordances the card freezes into its resolved state so the
// conversation transcript remains coherent.
export type SetupAgendaConfirmationResolution = 'confirmed' | 'not_quite' | 'skipped'

export interface SetupAgendaConfirmationRequest {
  id: string
  agendaItemId: string
  prompt: string
  createdAt: string
  resolution?: SetupAgendaConfirmationResolution
  resolvedAt?: string
}

// Mirror of the backend's `SetupAgendaItemMark` payload used by
// `agenda_item_marked` SSE events. Kept as a structural type rather
// than a class so the reducer can apply it directly.
export interface SetupAgendaItemMark {
  id: string
  status: SetupSessionAgendaItemStatus
  completionBasis?: string
}

// Re-engagement request the observation hook builds after the user
// resolves an inline AgendaConfirmationCard. Shaped to mirror the
// existing assistant-session / agent-task re-engagement contracts.
export interface SetupAgendaConfirmationResolvedTurnRequest {
  confirmationId: string
  agendaItemId: string
  resolution: SetupAgendaConfirmationResolution
  prompt: string
}

// Right-aligned acknowledgment chip rendered when the user resolves a
// structured inline interaction (consent receipts today, agenda
// confirmation cards as well). Distinct from a real user message:
// smaller chip footprint, no "You" label, filtered out of the agent's
// chat_history in useSetupAgentStream's buildRequest so the agent only
// ever sees the structured execution outcome, not a synthetic user
// utterance.
export type SetupUserAcknowledgmentKind = 'receipt_decision' | 'agenda_confirmation'
export type SetupUserAcknowledgmentDecision =
  | 'approved'
  | 'deferred'
  | 'skipped'
  | SetupAgendaConfirmationResolution

export interface SetupUserAcknowledgment {
  id: string
  sourceId: string
  kind: SetupUserAcknowledgmentKind
  decision: SetupUserAcknowledgmentDecision
  label: string
  createdAt: string
}

export type SetupStage = 'welcome' | 'intro_and_privacy' | 'orientation' | 'conversation' | 'wrap_up'

export interface SetupConversationMessage {
  id: string
  role: 'basil' | 'user' | 'system'
  content: string
  createdAt: string
  streaming?: boolean
  // Set on Basil messages that began streaming live in this session (message_started); the row paces their text in instead of painting it at once. Restored or synthesized messages leave it unset and render immediately.
  revealProgressively?: boolean
  inlineReceipts: SetupConsentReceipt[]
  inlineEmailContexts?: SetupInlineEmailContext[]
  inlineDillDrafts?: SetupInlineDillDraft[]
  inlineAgendaConfirmations?: SetupAgendaConfirmationRequest[]
  inlineVisuals?: SetupInlineVisual[]
  // Presence of this field marks the message as a user-action
  // acknowledgment chip rather than a typed utterance. BasilConversation
  // renders these with a smaller chip variant and no "You" label, and
  // useSetupAgentStream.buildRequest filters them out of chat_history
  // so the agent only sees the structured execution outcome.
  inlineAcknowledgment?: SetupUserAcknowledgment
}

export interface SetupPendingProposal {
  proposalId: string
  receipt: SetupConsentReceipt
  approvalState: SetupToolApprovalState
  statusMessage?: string | null
  errorMessage?: string | null
}

export interface SetupProgressNarration {
  message: string
  at: number
}

export interface SetupStreamActivity {
  label: string
  at: number
}

export interface SetupAssistantState {
  setupStage: SetupStage
  setupAgentModelAccess: SetupAgentModelAccess | null
  observations: SetupOrientationObservation[]
  messages: SetupConversationMessage[]
  activeArtifact?: SetupArtifact
  artifacts: SetupArtifact[]
  pendingProposals: Record<string, SetupPendingProposal>
  currentChips: SetupSuggestionChip[]
  isStreaming: boolean
  errorMessage?: string
  discoveryFacts: SetupDiscoveryFact[]
  wasSkipped: boolean
  wrapUpProposal?: SetupWrapUpProposal
  isFinalizingWrapUp: boolean
  finalizeError: string | null
  latestProgressNarration: SetupProgressNarration | null
  lastStreamActivity: SetupStreamActivity | null
  trackedAgentTasks: Record<string, SetupTrackedAgentTask>
  trackedAssistantSessions: Record<string, SetupTrackedAssistantSession>
  // Ordered list of agenda items; empty until the agent calls
  // propose_session_agenda for the first time. The sidebar renders
  // this list verbatim; status pills come from each item's `status`.
  sessionAgenda: SetupSessionAgendaItem[]
  // Map of confirmation-card id -> active request. Cards in this map
  // are also embedded into a conversation message via
  // inlineAgendaConfirmations for chronological rendering; this map
  // exists so the bridge router and reducer can look up a card by id
  // when the user resolves it, without scanning the message list.
  pendingAgendaConfirmations: Record<string, SetupAgendaConfirmationRequest>
  // Whether the user has collapsed the agenda sidebar this session.
  // Persisted only in memory (resets between launches) — heavy
  // persistence belongs to the broader "resume" effort that's out of
  // scope here.
  isAgendaSidebarCollapsed: boolean
}

// Internal contract between `types.ts` and `reducer.ts`. Intentionally not
// re-exported through the package barrel (`index.ts`) — consumers dispatch
// through the typed helpers on `useSetupAssistantStore()` and never need to
// know the action shape directly.
export type SetupAssistantAction =
  | { type: 'set_stage'; setupStage: SetupStage }
  | { type: 'set_model_access'; setupAgentModelAccess: SetupAgentModelAccess | null }
  | { type: 'append_user_message'; content: string }
  | { type: 'apply_event'; event: SetupAgentEvent }
  | { type: 'set_error'; errorMessage?: string }
  | {
    type: 'set_proposal_state'
    proposalId: string
    approvalState: SetupToolApprovalState
    statusMessage?: string | null
    errorMessage?: string | null
    appearanceChange?: SetupAppearanceChangeSummary | null
  }
  | { type: 'set_discovery_facts'; discoveryFacts: SetupDiscoveryFact[] }
  | { type: 'mark_setup_skipped' }
  | { type: 'set_is_finalizing_wrap_up'; isFinalizingWrapUp: boolean }
  | { type: 'set_finalize_error'; finalizeError: string | null }
  | { type: 'set_wrap_up_proposal'; proposal: SetupWrapUpProposal }
  | { type: 'register_tracked_agent_task'; agentTaskId: string }
  | {
    type: 'observe_tracked_agent_task'
    agentTaskId: string
    status: string
    resultMessage: string | null
    isTerminal: boolean
    observedAt: number
  }
  | { type: 'clear_tracked_agent_task'; agentTaskId: string }
  | { type: 'register_tracked_assistant_session'; assistantSessionId: string }
  | {
    type: 'observe_tracked_assistant_session'
    assistantSessionId: string
    status: string
    resultText: string | null
    isTerminal: boolean
    observedAt: number
  }
  | { type: 'clear_tracked_assistant_session'; assistantSessionId: string }
  | { type: 'add_inline_dill_draft'; draft: SetupInlineDillDraft }
  | { type: 'set_session_agenda'; items: SetupSessionAgendaItem[] }
  | { type: 'apply_agenda_marks'; marks: SetupAgendaItemMark[] }
  | {
    type: 'add_agenda_confirmation_request'
    confirmation: SetupAgendaConfirmationRequest
  }
  | {
    type: 'resolve_agenda_confirmation'
    confirmationId: string
    resolution: SetupAgendaConfirmationResolution
    resolvedAt: string
  }
  | { type: 'set_agenda_sidebar_collapsed'; collapsed: boolean }
  | { type: 'add_user_acknowledgment'; acknowledgment: SetupUserAcknowledgment }
