import { describeImportedContext } from '@/components/discovery/importedContextCard'
import type { SetupImportedContextSummary } from '@/state/setupAssistantStore'

export interface WrapUpSavedChoicesProps {
  /** The reply preferences that were saved to the profile during the first setup step. Empty when none were saved. */
  interactionStyle?: string[]
  /** What the person's import added during setup, or null when nothing was imported. */
  importedContext?: SetupImportedContextSummary | null
}

/**
 * Lists what setup saved that is not a reviewable proposal, so the wrap-up screen does not read as "nothing happened"
 * to someone who chose reply preferences or imported background earlier. Renders nothing when nothing was saved.
 */
export function WrapUpSavedChoices({ interactionStyle = [], importedContext = null }: WrapUpSavedChoicesProps) {
  const imported = describeImportedContext(importedContext)
  if (interactionStyle.length === 0 && !imported) return null

  return (
    <section className="setup-wrapup-saved-choices" aria-label="Saved during setup">
      <h2>Saved during setup</h2>
      {interactionStyle.length > 0 && (
        <>
          <p>Your reply preferences are saved to your profile, and Basil follows them in every conversation.</p>
          <ul>
            {interactionStyle.map((instruction, index) => (
              <li key={`${index}-${instruction}`}>{instruction}</li>
            ))}
          </ul>
        </>
      )}
      {imported && (
        <p className="setup-wrapup-saved-choices__imported">
          <strong>{imported.title}.</strong> {imported.detail}
        </p>
      )}
    </section>
  )
}
