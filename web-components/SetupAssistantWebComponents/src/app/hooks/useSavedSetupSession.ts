import { useEffect, useState } from 'react'

import { discardSavedSetupSession, fetchSetupAssistantState } from '@/services/api'
import type { useSetupAssistantStore } from '@/state/setupAssistantStore'

import { buildResumeSeedMessage, parseSavedSetupSession, type SavedSetupSession } from '../resume/savedSession'
import type { SetupAgentStreamApi } from './useSetupAgentStream'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

// Looks once, when the window opens, for a setup session that was left partway. While one is found and the person has not chosen yet, the first screen offers to pick it up or start from the top. Picking it up restores the agenda, the model choice, and the working style, then sends the agent one message that says what was covered. Nothing expires, so there is no age cutoff here: the screen only uses the age to decide which choice to lean toward.

export interface SavedSetupSessionApi {
  offeredSession: SavedSetupSession | null
  resume: () => void
  startOver: () => void
}

export function useSavedSetupSession({
  store,
  startStream,
  onResumed,
}: {
  store: SetupAssistantStore
  startStream: SetupAgentStreamApi['startStream']
  onResumed: () => void
}): SavedSetupSessionApi {
  const [offeredSession, setOfferedSession] = useState<SavedSetupSession | null>(null)
  const [pendingSeed, setPendingSeed] = useState<string | null>(null)

  useEffect(() => {
    let isCurrent = true
    void (async () => {
      try {
        const response = await fetchSetupAssistantState()
        if (isCurrent) setOfferedSession(parseSavedSetupSession(response.state))
      } catch {
        // Without a readable saved state the person simply sees the normal first screen.
      }
    })()
    return () => {
      isCurrent = false
    }
  }, [])

  // The request is built from the store, so the stream starts only after the restored model choice and agenda have landed in it.
  useEffect(() => {
    if (pendingSeed === null) return
    if (store.state.setupStage !== 'conversation' || !store.state.setupAgentModelAccess?.resolved) return
    const seed = pendingSeed
    setPendingSeed(null)
    startStream(seed, undefined, 'agent_synthesis', 'conversation')
  }, [pendingSeed, store.state.setupStage, store.state.setupAgentModelAccess, startStream])

  const resume = () => {
    if (!offeredSession) return
    onResumed()
    store.restoreSavedSession(offeredSession.modelAccess, offeredSession.agenda, offeredSession.interactionStyle)
    setPendingSeed(buildResumeSeedMessage(offeredSession))
    setOfferedSession(null)
  }

  // The saved session is forgotten on the backend as well, so closing the window right after choosing this does not bring the turned-down session back at the next launch. A failed request leaves the normal first screen in place, and the next progress save replaces the old session anyway.
  const startOver = () => {
    setOfferedSession(null)
    void discardSavedSetupSession().catch(() => undefined)
  }

  return { offeredSession, resume, startOver }
}
