import { useEffect, useRef, useState } from 'react'

import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import { useStickToBottom } from '@shared/useStickToBottom'
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
import { useHasUnfinishedReveal } from './usePacedText'

// The pause between the last word of a message and its suggested next steps appearing, so the chips land as a deliberate beat rather than alongside the text.
export const CHIP_REVEAL_DELAY_MS = 600

interface Props {
  messages: SetupConversationMessage[]
  chips: SetupSuggestionChip[]
  chipsMultiSelect?: boolean
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
  onApproveAll?: (proposalIds: string[]) => void
  onAgendaConfirmationResolved: (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => void
}

export function BasilConversation({
  messages,
  chips,
  chipsMultiSelect = false,
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
  onApproveAll,
  onAgendaConfirmationResolved,
}: Props) {
  const [draft, setDraft] = useState('')
  const [showObservations, setShowObservations] = useState(false)
  const [selectedChipIds, setSelectedChipIds] = useState<string[]>([])
  const [otherAnswer, setOtherAnswer] = useState('')
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

  const chipSignature = chips.map(chip => chip.id).join('|')
  useEffect(() => {
    setSelectedChipIds([])
    setOtherAnswer('')
  }, [chipSignature])

  // Chips wait for the whole turn to finish and for the message text to finish revealing, then hold for a short beat before they appear.
  const hasUnfinishedReveal = useHasUnfinishedReveal()
  const canOfferChips = chips.length > 0
    && !hasPendingReceiptAwaitingApproval
    && !isStreaming
    && !hasUnfinishedReveal
  const [chipsRevealed, setChipsRevealed] = useState(false)
  useEffect(() => {
    setChipsRevealed(false)
    if (!canOfferChips) return undefined
    const timer = setTimeout(() => setChipsRevealed(true), CHIP_REVEAL_DELAY_MS)
    return () => clearTimeout(timer)
  }, [canOfferChips, chipSignature])

  const toggleChip = (chipId: string) => {
    setSelectedChipIds(current => (
      current.includes(chipId) ? current.filter(id => id !== chipId) : [...current, chipId]
    ))
  }

  // A multi-select answer is the picked chips plus whatever the user typed into the panel's own "something else" field, sent together as one message.
  const trimmedOtherAnswer = otherAnswer.trim()
  const multiSelectAnswerCount = selectedChipIds.length + (trimmedOtherAnswer ? 1 : 0)

  const submitSelectedChips = () => {
    const selected = chips.filter(chip => selectedChipIds.includes(chip.id))
    const parts = selected.map(chip => chip.message.trim())
    if (trimmedOtherAnswer) parts.push(trimmedOtherAnswer)
    if (parts.length === 0) return
    setDraft('')
    setOtherAnswer('')
    onUserMessage(parts.join('\n'), selected[0]?.preliminaryStatusMessage)
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
              onApproveAll={onApproveAll}
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

      {canOfferChips && chipsRevealed && (
        <div className="chip-row" aria-label="Suggested next steps">
          <p className="eyebrow chip-row-label">
            {chipsMultiSelect ? 'Pick any that apply' : 'Suggested next steps'}
          </p>
          <div className="chip-row-buttons">
            {chips.map(chip => {
              const isSelected = selectedChipIds.includes(chip.id)
              return (
                <button
                  key={chip.id}
                  type="button"
                  className={`secondary-button${chipsMultiSelect ? ' chip-multi' : ''}${chipsMultiSelect && isSelected ? ' chip-selected' : ''}`}
                  aria-pressed={chipsMultiSelect ? isSelected : undefined}
                  onClick={() => (
                    chipsMultiSelect
                      ? toggleChip(chip.id)
                      : submitChipMessage(chip.message, chip.preliminaryStatusMessage)
                  )}
                  disabled={isStreaming}
                >
                  {chipsMultiSelect && <span className="chip-check" aria-hidden="true">✓</span>}
                  {plainMarkdownText(chip.label)}
                </button>
              )
            })}
          </div>
          {chipsMultiSelect && (
            <div className="chip-other">
              <label className="chip-other-label" htmlFor="chip-other-answer">
                Something else? <span className="chip-other-hint">Sent together with the options you picked.</span>
              </label>
              <div className="chip-other-controls">
                <textarea
                  id="chip-other-answer"
                  className="chip-other-input"
                  value={otherAnswer}
                  onChange={event => setOtherAnswer(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) {
                      event.preventDefault()
                      if (!isStreaming) submitSelectedChips()
                    }
                  }}
                  placeholder="Add anything these don't cover (⌘↩ to send)"
                  rows={2}
                />
                <button
                  type="button"
                  className="primary-button chip-send-selected"
                  onClick={submitSelectedChips}
                  disabled={isStreaming || multiSelectAnswerCount === 0}
                >
                  {multiSelectAnswerCount > 1 ? `Send ${multiSelectAnswerCount} answers` : 'Send answer'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="basil-input-row">
        <textarea
          value={draft}
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            // Command+Enter (Control+Enter off macOS) sends, matching the rest of Basil; plain Enter still adds a new line.
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submitDraft()
            }
          }}
          placeholder="Ask me anything, correct me, or take this somewhere new... (⌘↩ to send)"
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

