import type {
  SetupAgendaConfirmationRequest,
  SetupAgendaConfirmationResolution,
} from '@/state/setupAssistantStore'

import { SetupConversationMarkdown } from './SetupConversationMarkdown'

// Inline conversation card the agent surfaces after a literacy
// walkthrough or capability demo where completion isn't observable
// from any side-effect. Three structured affordances:
//
//   - Yes, that landed       -> resolution = 'confirmed'
//   - Not quite, keep going  -> resolution = 'not_quite'
//   - Skip this              -> resolution = 'skipped'
//
// Sibling of `InlineDillDraftCard` — same eyebrow + heading + body
// block + footer rhythm — so the conversation reads with consistent
// visual language across all inline cards. Once the user resolves
// the card, the buttons disappear and a frozen "you chose ..." line
// stands in so the transcript remains coherent on scrollback.
//
// The actual resolution work (updating the store, firing the
// re-engagement turn) lives in `useSetupObservations` —
// `AgendaConfirmationCard` itself is a presentational shell that
// invokes `onResolve(confirmationId, resolution)`.

interface Props {
  confirmation: SetupAgendaConfirmationRequest
  onResolve: (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => void
}

const RESOLUTION_LABELS: Record<SetupAgendaConfirmationResolution, string> = {
  confirmed: 'You said it landed.',
  not_quite: 'You said not quite.',
  skipped: 'You skipped this check.',
}

export function AgendaConfirmationCard({ confirmation, onResolve }: Props) {
  const isResolved = Boolean(confirmation.resolution)
  const stateClass = isResolved
    ? `state-resolved state-${confirmation.resolution}`
    : 'state-pending'

  return (
    <article
      className={`agenda-confirmation-card ${stateClass}`}
      aria-label={isResolved ? 'Agenda confirmation resolved' : 'Agenda confirmation pending'}
    >
      <header className="agenda-confirmation-header">
        <span className="agenda-confirmation-eyebrow">Quick check</span>
      </header>

      <div className="agenda-confirmation-prompt">
        <SetupConversationMarkdown content={confirmation.prompt} />
      </div>

      {!isResolved && (
        <footer className="agenda-confirmation-actions">
          <button
            type="button"
            className="primary-button agenda-confirmation-action confirm"
            onClick={() => onResolve(confirmation.id, 'confirmed')}
          >
            Yes, that landed
          </button>
          <button
            type="button"
            className="secondary-button agenda-confirmation-action not-quite"
            onClick={() => onResolve(confirmation.id, 'not_quite')}
          >
            Not quite, keep going
          </button>
          <button
            type="button"
            className="tertiary-button agenda-confirmation-action skip"
            onClick={() => onResolve(confirmation.id, 'skipped')}
          >
            Skip this
          </button>
        </footer>
      )}

      {isResolved && confirmation.resolution && (
        <p className="agenda-confirmation-resolution-line">
          {RESOLUTION_LABELS[confirmation.resolution]}
        </p>
      )}
    </article>
  )
}
