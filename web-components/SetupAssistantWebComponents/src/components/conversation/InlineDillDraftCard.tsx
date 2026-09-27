import { useState } from 'react'

import type { SetupInlineDillDraft } from '@/state/setupAssistantStore'

/*
 * Inline conversation card that represents a completed (or failed)
 * Dill draft from a setup-launched assistant session. Sibling of
 * `InlineEmailContextCard` — same eyebrow + heading + body block +
 * footer rhythm — so the conversation reads with consistent visual
 * language as the user's eye moves from "this is the email we're
 * working from" to "this is what Dill drafted against it".
 *
 * Read-only by design: the draft can be edited, saved, or discarded
 * inside the Dill widget itself (which is already open when the card
 * renders); duplicating those actions here would split the user's
 * attention and is explicitly out of scope for v1.
 */

interface Props {
  draft: SetupInlineDillDraft
}

const COLLAPSED_PREVIEW_CHARS = 360

export function InlineDillDraftCard({ draft }: Props) {
  const [expanded, setExpanded] = useState(false)

  const isFailed = draft.status === 'failed'
  const trimmedResult = (draft.resultText ?? '').trim()
  const canCollapse = trimmedResult.length > COLLAPSED_PREVIEW_CHARS
  const displayedBody = canCollapse && !expanded
    ? `${trimmedResult.slice(0, COLLAPSED_PREVIEW_CHARS)}…`
    : trimmedResult

  const heading = isFailed
    ? "Dill couldn't draft a reply"
    : 'Dill drafted a reply'

  const statusLabel = isFailed ? 'Failed' : 'Completed'

  const stateClass = isFailed ? 'state-failed' : 'state-completed'
  const ariaLabel = isFailed
    ? 'Dill draft failed'
    : 'Dill draft completed'

  return (
    <article
      className={`inline-dill-draft-card ${stateClass}`}
      aria-label={ariaLabel}
    >
      <header className="inline-dill-draft-header">
        <span className="inline-dill-draft-eyebrow">Dill draft</span>
        <span className="inline-dill-draft-status-pill">{statusLabel}</span>
      </header>

      <h3 className="inline-dill-draft-heading">{heading}</h3>
      {draft.applicationName && (
        <p className="inline-dill-draft-application">
          For {draft.applicationName}
        </p>
      )}

      {isFailed ? (
        <p className="inline-dill-draft-error">
          {draft.errorMessage?.trim() || 'Dill ran into an error while drafting. Try again, or pick a different email.'}
        </p>
      ) : trimmedResult.length === 0 ? (
        <p className="inline-dill-draft-hint">
          Dill finished, but the draft text didn't come back from the widget. Open Dill to see what it produced.
        </p>
      ) : (
        <pre
          className={`inline-dill-draft-body ${expanded ? 'is-expanded' : 'is-collapsed'}`}
          aria-label="Dill draft body"
        >{displayedBody}</pre>
      )}

      {(!isFailed && canCollapse) && (
        <footer className="inline-dill-draft-footer">
          <button
            type="button"
            className="secondary-button inline-dill-draft-toggle"
            onClick={() => setExpanded(value => !value)}
            aria-expanded={expanded}
          >
            {expanded ? 'Collapse' : 'Show full draft'}
          </button>
          <span className="inline-dill-draft-hint">
            Edit, save, or discard in the Dill widget.
          </span>
        </footer>
      )}
    </article>
  )
}
