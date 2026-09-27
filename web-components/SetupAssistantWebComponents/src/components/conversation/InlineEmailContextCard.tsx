import { useState } from 'react'

import type { SetupInlineEmailContext } from '@/types'

interface Props {
  context: SetupInlineEmailContext
}

const EXCERPT_COLLAPSED_CHARS = 600

export function InlineEmailContextCard({ context }: Props) {
  const [expanded, setExpanded] = useState(false)

  const trimmedBody = (context.body_excerpt ?? '').trim()
  const canCollapse = trimmedBody.length > EXCERPT_COLLAPSED_CHARS
  const displayedBody = canCollapse && !expanded
    ? `${trimmedBody.slice(0, EXCERPT_COLLAPSED_CHARS)}…`
    : trimmedBody

  const receivedLabel = context.received_at
    ? formatReceivedLabel(context.received_at)
    : null

  const subject = (context.subject ?? '').trim() || '(no subject)'
  const senderName = (context.sender_name ?? '').trim() || context.sender_address || 'Unknown sender'

  return (
    <article className="inline-email-context-card" aria-label={`Email from ${senderName}: ${subject}`}>
      <header className="inline-email-context-header">
        <span className="inline-email-context-eyebrow">
          Pulled from {context.client_name || 'your inbox'}
        </span>
        <h3 className="inline-email-context-subject">{subject}</h3>
        <p className="inline-email-context-meta">
          <span className="inline-email-context-sender">
            {senderName}
            {context.sender_address && context.sender_address !== senderName && (
              <span className="inline-email-context-sender-address"> &lt;{context.sender_address}&gt;</span>
            )}
          </span>
          {receivedLabel && (
            <>
              <span className="inline-email-context-dot" aria-hidden="true"> · </span>
              <time dateTime={context.received_at ?? undefined}>{receivedLabel}</time>
            </>
          )}
        </p>
      </header>

      <blockquote className="inline-email-context-body">
        {displayedBody.split('\n').filter(line => line.length > 0).map((line, index) => (
          <p key={`${context.email_id}-line-${index}`}>{line}</p>
        ))}
        {trimmedBody.length === 0 && (
          <p className="inline-email-context-empty">
            (No readable body — the message may be encrypted, image-only, or empty.)
          </p>
        )}
      </blockquote>

      {(canCollapse || context.excerpt_truncated) && (
        <footer className="inline-email-context-footer">
          {canCollapse && (
            <button
              type="button"
              className="secondary-button inline-email-context-toggle"
              onClick={() => setExpanded(value => !value)}
            >
              {expanded ? 'Collapse' : 'Show full excerpt'}
            </button>
          )}
          {context.excerpt_truncated && (
            <span className="inline-email-context-truncated">
              Excerpt — the full email is longer than what I'm showing here.
            </span>
          )}
        </footer>
      )}
    </article>
  )
}

function formatReceivedLabel(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
