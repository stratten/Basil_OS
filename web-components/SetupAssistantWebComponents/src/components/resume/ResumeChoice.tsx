import type { SavedSetupSession } from '@/app/resume/savedSession'
import { describeSessionAge, shouldSuggestStartingOver } from '@/app/resume/savedSession'

interface Props {
  session: SavedSetupSession
  onResume: () => void
  onStartOver: () => void
}

// Shown in place of the path chooser when a setup session was left partway. Nothing here expires: the person can always pick up where they left off. When the saved session is a few days old, the screen says so and leans toward starting from the top, without removing the other choice.
export function ResumeChoice({ session, onResume, onStartOver }: Props) {
  const suggestStartingOver = shouldSuggestStartingOver(session)
  const doneCount = session.agenda.filter(item => item.status === 'completed').length
  return (
    <section className="phase-section welcome-intro resume-choice" aria-labelledby="resume-choice-heading">
      <img className="welcome-intro-logo" src="/images/basil-logo.png" alt="" aria-hidden="true" />
      <p className="eyebrow">Setup assistant</p>
      <h2 id="resume-choice-heading">Welcome back.</h2>
      <div className="welcome-intro-copy">
        <p>
          You started setting up Basil {describeSessionAge(session.ageDays)}
          {session.agenda.length > 0 ? `, and we had finished ${doneCount} of ${session.agenda.length} things on the list` : ''}.
        </p>
      </div>
      {suggestStartingOver && (
        <p className="resume-choice-advisory" role="note">
          It has been a while since you started this, and things may have changed. I'd suggest starting from the top, but you can pick up where you left off if you prefer.
        </p>
      )}
      <div className="resume-choice-actions">
        <button
          type="button"
          className={suggestStartingOver ? 'secondary-button' : 'primary-button'}
          onClick={onResume}
        >
          Pick up where we left off
        </button>
        <button
          type="button"
          className={suggestStartingOver ? 'primary-button' : 'secondary-button'}
          onClick={onStartOver}
        >
          Start from the top
        </button>
      </div>
    </section>
  )
}
