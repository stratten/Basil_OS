import type { SetupLocalModelFailure } from '@/state/setupAssistantStore'

/** The setup problem that is still unresolved when the person reaches the wrap-up screen. */
export interface WrapUpProblem {
  message: string
  /** The native return code that Show logs and Report a problem attach, or null for a plain error with no code. */
  detail: string | null
}

/** Picks the problem to show on the wrap-up screen. A typed local model failure wins over a generic error, and a blank error is no problem at all. */
export function wrapUpProblemFrom(
  localModelFailure: SetupLocalModelFailure | undefined,
  errorMessage: string | null | undefined,
): WrapUpProblem | null {
  if (localModelFailure) return { message: localModelFailure.message, detail: localModelFailure.detail }
  const message = errorMessage?.trim()
  return message ? { message, detail: null } : null
}

export interface WrapUpProblemNoticeProps {
  problem: WrapUpProblem
  /** Saves a redacted diagnostics bundle and shows it in Finder. The button is hidden when this is not provided. */
  onShowLogs?: (detail?: string) => void
  /** Opens the Report a problem flow. The button is hidden when this is not provided. */
  onReport?: (detail?: string) => void
}

/**
 * Says what went wrong inside the wrap-up panel, in place of the setup error banner. The banner's Try again runs the last
 * conversation turn, which does nothing useful once the conversation is over, so only the two actions that still make sense remain.
 */
export function WrapUpProblemNotice({ problem, onShowLogs, onReport }: WrapUpProblemNoticeProps) {
  const detail = problem.detail ?? undefined
  return (
    <div className="setup-wrapup-problem" role="alert">
      <p className="setup-wrapup-problem__message">{problem.message}</p>
      {(onShowLogs || onReport) && (
        <div className="setup-wrapup-problem__actions">
          {onShowLogs && (
            <button type="button" className="secondary-button" onClick={() => onShowLogs(detail)}>
              Show logs
            </button>
          )}
          {onReport && (
            <button type="button" className="secondary-button" onClick={() => onReport(detail)}>
              Report a problem
            </button>
          )}
        </div>
      )}
    </div>
  )
}
