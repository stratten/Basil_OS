import { memo } from 'react'

import type { SetupPendingProposal } from '@/state/setupAssistantStore'
import type { SetupArtifact, SetupArtifactRow, SetupToolApprovalState } from '@/types'

import { AppearanceChangeSummaryCard } from './AppearanceChangeSummaryCard'

interface Props {
  artifact?: SetupArtifact
  pendingProposals: Record<string, SetupPendingProposal>
  onClose: (artifactId: string) => void
  onReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
}

function BasilArtifactPanelComponent({
  artifact,
  pendingProposals,
  onClose,
  onReceiptAction,
}: Props) {
  if (!artifact || !artifact.is_open) {
    return null
  }

  return (
    <aside className="artifact-panel" aria-label="Basil setup artifact">
      <div className="artifact-panel-header">
        <div>
          <p className="eyebrow">{artifact.kind.replace(/_/g, ' ')}</p>
          <h2>{artifact.title}</h2>
        </div>
        <button type="button" className="secondary-button" onClick={() => onClose(artifact.id)}>
          Close
        </button>
      </div>

      <div className="artifact-row-list">
        {artifact.rows.length > 0 ? (
          artifact.rows.map(row => (
            <ArtifactRowCard
              key={row.id}
              row={row}
              pendingProposals={pendingProposals}
              onReceiptAction={onReceiptAction}
            />
          ))
        ) : (
          <article className="info-card">
            <h3>I'm putting options together.</h3>
            <p>They'll show up here as I'm ready.</p>
          </article>
        )}
      </div>
    </aside>
  )
}

function artifactPanelPropsAreEqual(previous: Readonly<Props>, next: Readonly<Props>): boolean {
  if (
    previous.artifact !== next.artifact
    || previous.onClose !== next.onClose
    || previous.onReceiptAction !== next.onReceiptAction
  ) return false

  return previous.artifact?.rows
    .filter(row => row.receipt)
    .every((row) => (
      previous.pendingProposals[row.receipt!.proposal_id] === next.pendingProposals[row.receipt!.proposal_id]
    )) ?? true
}

export const BasilArtifactPanel = memo(BasilArtifactPanelComponent, artifactPanelPropsAreEqual)

function ArtifactRowCard({
  row,
  pendingProposals,
  onReceiptAction,
}: {
  row: SetupArtifactRow
  pendingProposals: Record<string, SetupPendingProposal>
  onReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
}) {
  const pendingProposal = row.receipt ? pendingProposals[row.receipt.proposal_id] : undefined
  const receipt = pendingProposal?.receipt ?? row.receipt
  const approvalState = pendingProposal?.approvalState ?? receipt?.approval_state
  const isBusy = approvalState === 'approving' || approvalState === 'executing'
  const canAct = approvalState === 'proposed' || approvalState === 'failed'
  const title = stringValue(row.payload.title) || stringValue(row.payload.display_name) || 'Setup option'
  const whyThisMightMatter = stringValue(row.payload.why_this_might_matter)
  const recommendedNextStep = stringValue(row.payload.recommended_next_step)
  const deferMessage = stringValue(row.payload.defer_message)
  const exampleUseCases = arrayOfStrings(row.payload.example_use_cases)
  const detail = whyThisMightMatter
    || stringValue(row.payload.detail)
    || stringValue(row.payload.rationale)
    || stringValue(row.payload.description)
    || stringValue(row.payload.expected_output)
    || 'I think this may be useful.'

  return (
    <article className="info-card artifact-row-card">
      <h3>{title}</h3>
      <p>{detail}</p>
      {exampleUseCases.length > 0 && (
        <div className="artifact-row-examples">
          <span className="eyebrow">Examples</span>
          <ul>
            {exampleUseCases.map(example => (
              <li key={example}>{example}</li>
            ))}
          </ul>
        </div>
      )}
      {recommendedNextStep && (
        <p>
          <strong>Recommended next step: </strong>
          {recommendedNextStep}
        </p>
      )}
      {deferMessage && (
        <p>
          <strong>Can wait: </strong>
          {deferMessage}
        </p>
      )}
      {receipt && approvalState && (
        <div className="button-row">
          <span className="status-chip">{formatApprovalState(approvalState)}</span>
          {receipt.ui_status_message && (
            <p className="receipt-status-message">{receipt.ui_status_message}</p>
          )}
          {receipt.ui_error_message && (
            <p className="receipt-error-message" role="alert">{receipt.ui_error_message}</p>
          )}
          {receipt.appearance_change && (
            <AppearanceChangeSummaryCard summary={receipt.appearance_change} />
          )}
          {isBusy && <span className="receipt-progress" aria-hidden="true" />}
          <button
            type="button"
            className="primary-button"
            onClick={() => onReceiptAction(receipt.proposal_id, 'approved')}
            disabled={!canAct}
          >
            {approvalState === 'failed' ? 'Try again' : 'Approve'}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => onReceiptAction(receipt.proposal_id, 'deferred')}
            disabled={approvalState !== 'proposed'}
          >
            Later
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => onReceiptAction(receipt.proposal_id, 'skipped')}
            disabled={approvalState !== 'proposed'}
          >
            Skip
          </button>
        </div>
      )}
    </article>
  )
}

function formatApprovalState(state: SetupToolApprovalState): string {
  return state.replace(/_/g, ' ')
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function arrayOfStrings(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.filter((item): item is string => typeof item === 'string')
}

