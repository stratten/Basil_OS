import { useMemo } from 'react'

import { ProfileImportPanel } from '@shared/contextImport/ProfileImportPanel'
import type { ProfileImportOutcome } from '@shared/contextImport/ProfileImportPanel'

import { setupContextImportClient } from '@/services/api'
import type { SetupImportedContextSummary } from '@/state/setupAssistantStore'
import type { SetupAgentModelAccess } from '@/types'

import { importRouteNotice } from './importRouteNotice'

interface Props {
  /** The route confirmed on the model step. When it is missing or unresolved, the backend uses the Settings memory model. */
  modelAccess: SetupAgentModelAccess | null
  onContextImported?: (summary: SetupImportedContextSummary) => void
  onContextImportUndone?: () => void
}

/** What the setup conversation learns from a saved profile import: that it happened and one sentence about it, never the text. */
export function summarizeProfileImport(outcome: ProfileImportOutcome): SetupImportedContextSummary | null {
  if (outcome.filesUpdated.length === 0) return null
  return {
    entries_added: 0,
    facts_proposed: 0,
    fact_titles: [],
    note_titles: [],
    profile_updated: true,
    profile_summary: outcome.summary,
  }
}

/** The optional import inside the learning step. Collapsed by default, so it never slows down someone who has nothing to bring. */
export function IntroContextImport({ modelAccess, onContextImported, onContextImportUndone }: Props) {
  const client = useMemo(setupContextImportClient, [])
  const resolvedAccess = modelAccess?.resolved
    ? {
        mode: modelAccess.mode,
        local_model_id: modelAccess.local_model_id ?? null,
        provider: modelAccess.provider ?? null,
        model_id: modelAccess.model_id ?? null,
        resolved: true,
      }
    : null

  return (
    <details className="intro-context-import">
      <summary>Optional: bring in what you already have</summary>
      <p className="intro-step-lede">
        Notes about you, a profile you wrote, or a memory export from another app. I will skip questions your import already answers. To bring in individual memories or activity captures one at a time, do that afterward in <em>Personalization &gt; Personal Context</em>.
      </p>
      <ProfileImportPanel
        client={client}
        routeNotice={importRouteNotice(modelAccess)}
        modelAccess={resolvedAccess}
        onImported={outcome => {
          const summary = summarizeProfileImport(outcome)
          if (summary) onContextImported?.(summary)
        }}
        onUndone={onContextImportUndone}
      />
    </details>
  )
}
