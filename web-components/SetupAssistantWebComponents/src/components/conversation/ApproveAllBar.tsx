import { useRef } from 'react'

import { SetupCardReveal } from './SetupCardReveal'

// Shown above a group of receipts so several waiting changes can be approved with one click. It stays mounted while the group has two or more receipts and simply folds away once fewer than two are still waiting, so the cards below it ease up instead of jumping.
export function ApproveAllBar({
  waitingCount,
  onApproveAll,
}: {
  waitingCount: number
  onApproveAll: () => void
}) {
  const lastShownCountRef = useRef(waitingCount)
  const visible = waitingCount >= 2
  if (visible) lastShownCountRef.current = waitingCount
  const shownCount = visible ? waitingCount : lastShownCountRef.current

  return (
    <SetupCardReveal collapsed={!visible}>
      <div className="receipt-batch-bar" role="group" aria-label="Approve all waiting changes">
        <p className="receipt-batch-bar-text">
          {shownCount} changes are waiting for your approval. You can also decide on each one below.
        </p>
        <button
          type="button"
          className="primary-button receipt-batch-bar-button"
          onClick={onApproveAll}
          disabled={!visible}
          tabIndex={visible ? undefined : -1}
        >
          {`Approve all ${shownCount}`}
        </button>
      </div>
    </SetupCardReveal>
  )
}
