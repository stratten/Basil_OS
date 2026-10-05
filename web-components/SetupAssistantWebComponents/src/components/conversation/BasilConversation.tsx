import { useEffect, useRef, useState } from 'react'

import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import { useStickToBottom } from '@/components/motion/useStickToBottom'
import type {
  SetupAgendaConfirmationResolution,
  SetupConversationMessage,
  SetupPendingProposal,
  SetupTrackedAgentTask,
  SetupTrackedAssistantSession,
} from '@/state/setupAssistantStore'
import type {
  SetupOrientationObservation,
  SetupSuggestionChip,
  SetupToolApprovalState,
} from '@/types'

import { SetupConversationMarkdown } from './SetupConversationMarkdown'
import { SetupConversationMessageRow } from './SetupConversationMessageRow'
import { plainMarkdownText } from '@shared/plainMarkdownText'

interface Props {
  messages: SetupConversationMessage[]
  chips: SetupSuggestionChip[]
  observations: SetupOrientationObservation[]
  pendingProposals: Record<string, SetupPendingProposal>
  isStreaming: boolean
  workingPrimaryLabel?: string | null
  workingActivityLabel?: string | null
  trackedAgentTasks?: Record<string, SetupTrackedAgentTask>
  trackedAssistantSessions?: Record<string, SetupTrackedAssistantSession>
  holdMessageReveal?: boolean
  onUserMessage: (content: string, preliminaryStatusMessage?: string | null) => void
  onReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
  onAgendaConfirmationResolved: (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => void
}

export function BasilConversation({
  messages,
  chips,
  observations,
  pendingProposals,
  isStreaming,
  workingPrimaryLabel,
  workingActivityLabel,
  trackedAgentTasks,
  trackedAssistantSessions,
  holdMessageReveal = false,
  onUserMessage,
  onReceiptAction,
  onAgendaConfirmationResolved,
}: Props) {
  const [draft, setDraft] = useState('')
  const [showObservations, setShowObservations] = useState(false)
  const observationsRef = useRef<HTMLDivElement>(null)
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const messagesStackRef = useRef<HTMLDivElement>(null)
  useStickToBottom(messagesScrollRef, messagesStackRef)

  useEffect(() => {
    if (!showObservations) return
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!observationsRef.current?.contains(event.target as Node)) setShowObservations(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowObservations(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [showObservations])

  const visibleMessages = messages.filter(message => (
    message.content.trim().length > 0
    || message.inlineReceipts.length > 0
    || (message.inlineEmailContexts?.length ?? 0) > 0
    || (message.inlineDillDrafts?.length ?? 0) > 0
    || (message.inlineAgendaConfirmations?.length ?? 0) > 0
    || (message.inlineVisuals?.length ?? 0) > 0
    || message.inlineAcknowledgment !== undefined
  ))
  const inFlightAgentTaskCount = trackedAgentTasks
    ? Object.values(trackedAgentTasks).filter(task => !task.isTerminal).length
    : 0
  const showAgentTaskInflightLine = inFlightAgentTaskCount > 0 && !isStreaming
  const agentTaskInflightLabel = inFlightAgentTaskCount > 1
    ? `Paprika is running ${inFlightAgentTaskCount} tasks for you...`
    : 'Paprika is running your task...'

  // Sibling of the Paprika inflight indicator, driven by the
  // trackedAssistantSessions slice the prior plan added. Surfaces the
  // gap between Approve and the terminal observation arriving back
  // through the bridge — without this, the conversation looks frozen
  // between those events even though Dill is actively drafting in the
  // widget. Hidden while `isStreaming` is true so it never doubles up
  // with the agent's own working indicator during the re-engagement
  // turn that fires immediately after terminal lands.
  const inFlightAssistantSessionCount = trackedAssistantSessions
    ? Object.values(trackedAssistantSessions).filter(session => !session.isTerminal).length
    : 0
  const showAssistantSessionInflightLine = inFlightAssistantSessionCount > 0 && !isStreaming
  const assistantSessionInflightLabel = inFlightAssistantSessionCount > 1
    ? `Waiting for Dill to finish drafting ${inFlightAssistantSessionCount} replies...`
    : 'Waiting for Dill to finish drafting your reply...'

  // Chips and a consent receipt that's awaiting the user's decision are two
  // competing response surfaces. The receipt's own Approve / Not now /
  // Suggest-something-else buttons own the user's next action while a
  // proposal is live; rendering parallel "Suggested next steps" chips
  // fragments attention and (worst-case) presents alternatives that
  // compete with the receipt instead of following it. We hide the chip
  // row whenever any proposal is in the `proposed` state so the receipt
  // stays the unambiguous focal point until the user acts on it.
  const hasPendingReceiptAwaitingApproval = Object.values(pendingProposals).some(
    proposal => proposal.approvalState === 'proposed'
  )

  const submitDraft = () => {
    const trimmed = draft.trim()
    if (!trimmed) return
    onUserMessage(trimmed)
    setDraft('')
  }

  const submitChipMessage = (
    message: string,
    preliminaryStatusMessage?: string | null,
  ) => {
    setDraft('')
    onUserMessage(message, preliminaryStatusMessage)
  }

  return (
    <section className="basil-conversation" aria-label="Basil setup conversation">
      <div className="basil-panel-header">
        <div>
          <p className="eyebrow">Setup · Conversation</p>
          <h2>What are you working on?</h2>
        </div>
        {observations.length > 0 && (
          <div ref={observationsRef} className="conversation-observations">
            <button
              type="button"
              className="secondary-button conversation-observations-toggle"
              aria-expanded={showObservations}
              aria-controls="conversation-observations-popover"
              onClick={() => setShowObservations(value => !value)}
            >
              {showObservations
                ? 'Hide setup notes'
                : `Setup notes (${observations.length})`}
            </button>
            {showObservations && (
              <section
                id="conversation-observations-popover"
                className="conversation-observations-popover"
                aria-label="Setup notes"
              >
                <div className="fact-list conversation-observation-list">
                  {observations.map(observation => (
                    <article key={observation.id} className="info-card conversation-observation-card">
                      <span className="eyebrow">{observation.label}</span>
                      <h3>{plainMarkdownText(observation.title)}</h3>
                      <SetupConversationMarkdown content={observation.detail} />
                    </article>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>

      <div ref={messagesScrollRef} className="basil-messages">
        <div ref={messagesStackRef} className="basil-messages-stack">
          {visibleMessages.map(message => (
            <SetupConversationMessageRow
              key={message.id}
              message={message}
              pendingProposals={pendingProposals}
              holdReveal={holdMessageReveal}
              onReceiptAction={onReceiptAction}
              onAgendaConfirmationResolved={onAgendaConfirmationResolved}
            />
          ))}

          {isStreaming && (
            <SetupWorkingIndicator
              label={workingPrimaryLabel ?? "I'm working on the next setup step."}
              detail={workingActivityLabel}
            />
          )}

          {showAgentTaskInflightLine && (
            <SetupWorkingIndicator
              className="conversation-agent-task-inflight"
              label={agentTaskInflightLabel}
              quiet
            />
          )}

          {showAssistantSessionInflightLine && (
            <SetupWorkingIndicator
              className="conversation-assistant-session-inflight"
              label={assistantSessionInflightLabel}
              quiet
            />
          )}
        </div>
      </div>

      {chips.length > 0 && !hasPendingReceiptAwaitingApproval && (
        <div className="chip-row" aria-label="Suggested next steps">
          <p className="eyebrow chip-row-label">Suggested next steps</p>
          <div className="chip-row-buttons">
            {chips.map(chip => (
              <button
                key={chip.id}
                type="button"
                className="secondary-button"
                onClick={() => submitChipMessage(chip.message, chip.preliminaryStatusMessage)}
                disabled={isStreaming}
              >
                {plainMarkdownText(chip.label)}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="basil-input-row">
        <textarea
          value={draft}
          onChange={event => setDraft(event.target.value)}
          placeholder="Ask me anything, correct me, or take this somewhere new..."
          rows={3}
        />
        <button
          type="button"
          className="primary-button"
          onClick={submitDraft}
        >
          Send
        </button>
      </div>
    </section>
  )
}

