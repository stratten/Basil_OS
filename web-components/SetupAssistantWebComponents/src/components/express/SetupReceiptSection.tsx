import { useEffect, useState } from 'react'

import { fetchExpressReceipt } from '@/services/api'

import type { ReceiptState, SetupReceipt } from './expressTypes'

const STATE_LABELS: Record<ReceiptState, string> = {
  on: 'On',
  partial: 'Partly on',
  off: 'Off',
}

interface Props {
  /** Change this to read the receipt again, for example after a download finishes. */
  refreshKey?: string
}

/** What is on right now, read from the real settings and installed models, with where to change each item. It renders nothing when the receipt cannot be read, rather than showing a stale list. */
export function SetupReceiptSection({ refreshKey = '' }: Props) {
  const [receipt, setReceipt] = useState<SetupReceipt | null>(null)

  useEffect(() => {
    let isCurrent = true
    void fetchExpressReceipt()
      .then((value) => { if (isCurrent) setReceipt(value) })
      .catch(() => { if (isCurrent) setReceipt(null) })
    return () => {
      isCurrent = false
    }
  }, [refreshKey])

  if (!receipt || receipt.items.length === 0) return null

  return (
    <section className="express-receipt" aria-label="What is on right now">
      <h2 className="express-receipt-title">What's on right now</h2>
      <ul className="express-receipt-list">
        {receipt.items.map(item => (
          <li key={item.id} className={`express-receipt-row express-receipt-row--${item.state}`}>
            <span className="express-receipt-state">{STATE_LABELS[item.state]}</span>
            <span className="express-receipt-body">
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
              <span className="express-receipt-where">Change it in {item.where_to_change}.</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
