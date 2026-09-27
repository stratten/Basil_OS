import { memo } from 'react'

import type {
  SetupAgendaConfirmationResolution,
  SetupConversationMessage,
  SetupPendingProposal,
} from '@/state/setupAssistantStore'
import type {
  SetupConsentReceipt,
  SetupToolApprovalState,
} from '@/types'

import { AgendaConfirmationCard } from './AgendaConfirmationCard'
import { AppearanceChangeSummaryCard } from './AppearanceChangeSummaryCard'
import { InlineDillDraftCard } from './InlineDillDraftCard'
import { InlineEmailContextCard } from './InlineEmailContextCard'
import { InlineSetupVisualCard } from './InlineSetupVisualCard'
import { SetupConversationMarkdown } from './SetupConversationMarkdown'

interface SetupConversationMessageRowProps {
  message: SetupConversationMessage
  pendingProposals: Record<string, SetupPendingProposal>
  onReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
  onAgendaConfirmationResolved: (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => void
}

function SetupConversationMessageRowComponent({
  message,
  pendingProposals,
  onReceiptAction,
  onAgendaConfirmationResolved,
}: SetupConversationMessageRowProps) {
  // User-action acknowledgment chip: short-circuits the normal
  // message render path because it carries no content, no
  // "You" label, and no inline child cards — it's purely a
  // right-aligned record that the user resolved a structured
  // inline interaction. Styled by .is-acknowledgment in
  // setup-assistant.conversation.messages.css. See the
  // inlineAcknowledgment field doc comment in
  // setupAssistantStore/types.ts.
  if (message.inlineAcknowledgment) {
    const ack = message.inlineAcknowledgment
    return (
      <article
        className={[
          'basil-message user is-acknowledgment',
          `ack-kind-${ack.kind}`,
          `decision-${ack.decision}`,
        ].join(' ')}
        aria-label={`You chose ${ack.label.replace(/\.$/, '').toLowerCase()}`}
      >
        <span className="user-acknowledgment-chip">
          <span className="user-acknowledgment-dot" aria-hidden="true" />
          {ack.label}
        </span>
      </article>
    )
  }

  return (
    <article className={`basil-message ${message.role}`}>
      {message.role === 'user' && <span>You</span>}
      <div className="basil-message-content">
        <SetupConversationMarkdown content={message.content} />
      </div>
      {(message.inlineEmailContexts ?? []).map(context => (
        <InlineEmailContextCard
          key={`${message.id}-${context.email_id}`}
          context={context}
        />
      ))}
      {(message.inlineDillDrafts ?? []).map(draft => (
        <InlineDillDraftCard
          key={`${message.id}-${draft.assistantSessionId}`}
          draft={draft}
        />
      ))}
      {(message.inlineVisuals ?? []).map(visual => (
        <InlineSetupVisualCard
          key={`${message.id}-${visual.id}`}
          visual={visual}
        />
      ))}
      {(message.inlineAgendaConfirmations ?? []).map(confirmation => (
        <AgendaConfirmationCard
          key={`${message.id}-${confirmation.id}`}
          confirmation={confirmation}
          onResolve={onAgendaConfirmationResolved}
        />
      ))}
      {message.inlineReceipts.map(receipt => (
        <ConsentReceiptCard
          key={receipt.id}
          receipt={receipt}
          pendingProposal={pendingProposals[receipt.proposal_id]}
          onReceiptAction={onReceiptAction}
        />
      ))}
    </article>
  )
}

function messageRowPropsAreEqual(
  previous: Readonly<SetupConversationMessageRowProps>,
  next: Readonly<SetupConversationMessageRowProps>,
): boolean {
  if (
    previous.message !== next.message
    || previous.onReceiptAction !== next.onReceiptAction
    || previous.onAgendaConfirmationResolved !== next.onAgendaConfirmationResolved
  ) return false

  return previous.message.inlineReceipts.every((receipt) => (
    previous.pendingProposals[receipt.proposal_id] === next.pendingProposals[receipt.proposal_id]
  ))
}

export const SetupConversationMessageRow = memo(
  SetupConversationMessageRowComponent,
  messageRowPropsAreEqual,
)

function ConsentReceiptCard({
  receipt,
  pendingProposal,
  onReceiptAction,
}: {
  receipt: SetupConsentReceipt
  pendingProposal?: SetupPendingProposal
  onReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
}) {
  const displayReceipt = pendingProposal?.receipt ?? receipt
  const approvalState = pendingProposal?.approvalState ?? displayReceipt.approval_state
  const isBusy = approvalState === 'approving' || approvalState === 'executing'
  const canAct = approvalState === 'proposed' || approvalState === 'failed'

  return (
    <article className={`info-card consent-receipt state-${approvalState}`}>
      <h3>{displayReceipt.title}</h3>
      <SetupConversationMarkdown content={displayReceipt.rationale} />
      <span className="status-chip">{formatApprovalState(approvalState)}</span>
      {displayReceipt.ui_status_message && (
        <p className="receipt-status-message">{displayReceipt.ui_status_message}</p>
      )}
      {displayReceipt.ui_error_message && (
        <p className="receipt-error-message" role="alert">{displayReceipt.ui_error_message}</p>
      )}
      {displayReceipt.appearance_change && (
        <AppearanceChangeSummaryCard summary={displayReceipt.appearance_change} />
      )}
      {isBusy && (
        <span className="receipt-progress" aria-hidden="true" />
      )}
      <div className="button-row">
        <button
          type="button"
          className="primary-button"
          onClick={() => onReceiptAction(displayReceipt.proposal_id, 'approved')}
          disabled={!canAct}
        >
          {approvalState === 'failed' ? 'Try again' : 'Approve'}
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => onReceiptAction(displayReceipt.proposal_id, 'deferred')}
          disabled={approvalState !== 'proposed'}
        >
          Not now
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => onReceiptAction(displayReceipt.proposal_id, 'skipped')}
          disabled={approvalState !== 'proposed'}
        >
          Suggest something else
        </button>
      </div>
    </article>
  )
}

function formatApprovalState(state: SetupToolApprovalState): string {
  return state.replace(/_/g, ' ')
}
