/*
 * Message bubble placement helpers
 *
 * The five helpers in this file all answer the same question: "I have
 * something new to attach to the conversation timeline — does it
 * belong inside the active Basil bubble, or in a fresh one?" The
 * answer depends on what just happened in the conversation:
 *
 *   - When the agent is mid-stream (the last message is from Basil
 *     and is part of the current turn), inline cards usually attach
 *     to that active bubble so the spoken text and the supporting
 *     card render as one cohesive turn. `addInlineReceipt`,
 *     `addInlineEmailContext`, and `addInlineSetupVisual` follow
 *     this rule.
 *
 *   - When the new attachment is itself a discrete event happening
 *     *now* (the user resolved a receipt; a launched Dill draft
 *     completed; the agent asked a follow-up question), the helper
 *     always opens a fresh bubble so the chronology reads correctly
 *     ("the draft existed after the user approved", not before).
 *     `addInlineDillDraft` and `addUserAcknowledgment` follow this
 *     rule unconditionally.
 *
 *   - When the active bubble is from the user instead of from
 *     Basil, the attach-vs-fresh helpers all open a fresh Basil
 *     bubble so the new content doesn't back-attach into a bubble
 *     that visually pre-dates the user's input.
 *
 * Per-helper doc comments below capture the specific rationale for
 * each card kind (most importantly, why some always-fresh helpers
 * intentionally skip the "is the last message from Basil?" check).
 *
 * Sibling files in the same `helpers/` folder:
 *   - setupAgentEventReducer.ts     (calls into addInline{Receipt,EmailContext,SetupVisual} for SSE events)
 *   - proposalAndArtifactHelpers.ts (artifact + proposal/receipt slice mutators)
 *   - agendaHelpers.ts              (agenda slice mutators)
 *   - ssePayloadNormalizers.ts      (SSE payload trust-boundary converters)
 *
 * The parent `reducer.ts` lives one level up and imports
 * addInlineDillDraft + addUserAcknowledgment from this file via
 * `./helpers/messageBubbleHelpers`.
 */

import type {
  SetupConsentReceipt,
  SetupInlineEmailContext,
  SetupInlineVisual,
} from '@/types'

import type {
  SetupAssistantState,
  SetupInlineDillDraft,
  SetupUserAcknowledgment,
} from '../types'


export function addInlineReceipt(
  state: SetupAssistantState,
  receipt?: SetupConsentReceipt,
): SetupAssistantState {
  if (!receipt) return state
  const proposalId = receipt.proposal_id
  const pendingProposals = {
    ...state.pendingProposals,
    [proposalId]: {
      proposalId,
      receipt,
      approvalState: receipt.approval_state,
    },
  }

  const lastMessage = state.messages[state.messages.length - 1]
  // Attach to the active Basil turn when the last message is from Basil. If
  // the user has spoken (or chip-clicked) since the last Basil message, append
  // a new Basil entry so the receipt visually shows up after the user input
  // instead of back-attaching into the previous Basil bubble.
  if (lastMessage && lastMessage.role === 'basil') {
    return {
      ...state,
      pendingProposals,
      messages: state.messages.map(message => (
        message.id === lastMessage.id
          ? { ...message, inlineReceipts: [...message.inlineReceipts, receipt] }
          : message
      )),
    }
  }

  return {
    ...state,
    pendingProposals,
    messages: [
      ...state.messages,
      {
        id: `basil-receipt-${proposalId}-${Date.now()}`,
        role: 'basil',
        content: '',
        createdAt: new Date().toISOString(),
        inlineReceipts: [receipt],
      },
    ],
  }
}

export function addInlineEmailContext(
  state: SetupAssistantState,
  context?: SetupInlineEmailContext,
): SetupAssistantState {
  if (!context || !context.email_id) return state
  const lastMessage = state.messages[state.messages.length - 1]

  // Mirrors addInlineReceipt's placement logic: attach to the active Basil
  // turn when the last message was Basil's, otherwise append a fresh Basil
  // entry so the pulled email appears after whatever the user just said,
  // not back-attached into a previous bubble.
  if (lastMessage && lastMessage.role === 'basil') {
    return {
      ...state,
      messages: state.messages.map(message => (
        message.id === lastMessage.id
          ? {
            ...message,
            inlineEmailContexts: [
              ...(message.inlineEmailContexts ?? []),
              context,
            ],
          }
          : message
      )),
    }
  }

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: `basil-email-context-${context.email_id}-${Date.now()}`,
        role: 'basil',
        content: '',
        createdAt: new Date().toISOString(),
        inlineReceipts: [],
        inlineEmailContexts: [context],
      },
    ],
  }
}

/*
 * Insert a Dill-draft card into the conversation timeline as its own
 * fresh Basil bubble — always. Unlike `addInlineEmailContext` (which
 * attaches mid-stream while the agent is actively composing a turn
 * about that very email), the Dill draft arrives at the end of a
 * side-effectful chain: user approves the receipt -> bridge launches
 * Dill -> Dill streams and completes -> terminal observation comes
 * back. By the time the terminal lands, the most recent Basil message
 * is the one that proposed the action and carries the (now-executed)
 * receipt; attaching there would render the draft card visually
 * above the receipt inside the same bubble, which reads as "the draft
 * existed before the user approved" — backwards.
 *
 * Putting the draft in its own bubble gives the correct chronological
 * sequence: receipt-bearing bubble -> draft bubble -> re-engagement
 * commentary bubble. The card carries its own copy of
 * `resultText`/`errorMessage` so it remains stable after the
 * corresponding `trackedAssistantSessions` entry is cleared by the
 * terminal handler.
 */
export function addInlineDillDraft(
  state: SetupAssistantState,
  draft?: SetupInlineDillDraft,
): SetupAssistantState {
  if (!draft || !draft.assistantSessionId) return state

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: `basil-dill-draft-${draft.assistantSessionId}-${Date.now()}`,
        role: 'basil',
        content: '',
        createdAt: new Date().toISOString(),
        inlineReceipts: [],
        inlineDillDrafts: [draft],
      },
    ],
  }
}

/*
 * Append a right-aligned user-action acknowledgment chip to the
 * conversation timeline as its own fresh `user`-role bubble. Mirrors
 * `addInlineDillDraft`'s placement rationale: the acknowledgment marks
 * a discrete user action happening *now* in response to an inline
 * interaction that's already on screen, so back-attaching the chip into
 * a prior bubble would visually pre-date the decision itself. Always
 * appended new.
 *
 * The bubble carries empty content and an `inlineAcknowledgment`
 * payload; BasilConversation special-cases the render path to produce
 * a small chip variant (no "You" label, no markdown content), and
 * useSetupAgentStream.buildRequest filters these messages out of
 * chat_history so the agent only ever sees the structured execution
 * outcome instead of a synthetic "Approved." / "Makes sense." user
 * utterance that would either fight or duplicate that signal.
 */
export function addUserAcknowledgment(
  state: SetupAssistantState,
  ack?: SetupUserAcknowledgment,
): SetupAssistantState {
  if (!ack || !ack.id) return state

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: `user-ack-${ack.id}`,
        role: 'user',
        content: '',
        createdAt: ack.createdAt,
        inlineReceipts: [],
        inlineAcknowledgment: ack,
      },
    ],
  }
}

/*
 * Inline setup-visual cards attach to the active Basil turn mid-stream,
 * mirroring `addInlineEmailContext`'s placement logic. The agent
 * typically calls `say` and then `show_setup_visual` in the same turn
 * (e.g. "here's how the menu bar icon changes when I'm recording" +
 * the actual screenshot pair), so the visual belongs inside that
 * Basil bubble, beneath the spoken text. When the last message is
 * from the user instead, we open a fresh Basil bubble so the visual
 * doesn't back-attach into a pre-user-input bubble.
 */
export function addInlineSetupVisual(
  state: SetupAssistantState,
  visual?: SetupInlineVisual,
): SetupAssistantState {
  if (!visual || !visual.id) return state
  const lastMessage = state.messages[state.messages.length - 1]

  if (lastMessage && lastMessage.role === 'basil') {
    return {
      ...state,
      messages: state.messages.map(message => (
        message.id === lastMessage.id
          ? {
            ...message,
            inlineVisuals: [
              ...(message.inlineVisuals ?? []),
              visual,
            ],
          }
          : message
      )),
    }
  }

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: `basil-visual-${visual.id}-${Date.now()}`,
        role: 'basil',
        content: '',
        createdAt: new Date().toISOString(),
        inlineReceipts: [],
        inlineVisuals: [visual],
      },
    ],
  }
}
