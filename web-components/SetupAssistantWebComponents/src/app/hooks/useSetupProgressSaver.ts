import { useEffect, useRef } from 'react'

import { saveSetupProgress } from '@/services/api'
import type { useSetupAssistantStore } from '@/state/setupAssistantStore'

import { buildProgressPayload } from '../resume/progressPayload'
import { trackProgressSave } from '../resume/progressSaveGate'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

// Keeps the session's place in the backend as it goes: every time the stage, the agenda, or what setup has done changes, after a short pause so a burst of changes is one save. Closing the window any way at all, not only through Skip, leaves a session that can be picked up. Nothing is saved before orientation or before a thinking model is chosen, because there is nothing to pick up yet. A failed save is retried by the next change and never interrupts the person.

export const PROGRESS_SAVE_DELAY_MS = 600

export function useSetupProgressSaver({ store }: { store: SetupAssistantStore }): void {
  const payload = buildProgressPayload(store.state)
  const serialized = payload === null ? null : JSON.stringify(payload)
  const lastSavedRef = useRef<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    pendingRef.current = null
    if (serialized === null || serialized === lastSavedRef.current) return undefined
    const toSave = serialized
    pendingRef.current = toSave
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      pendingRef.current = null
      trackProgressSave(saveSetupProgress(JSON.parse(toSave)))
        .then(() => { lastSavedRef.current = toSave })
        .catch(() => { /* the next change saves again */ })
    }, PROGRESS_SAVE_DELAY_MS)
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [serialized])

  // A change made in the last moments before the window closes is saved on the way out.
  useEffect(() => {
    const flush = () => {
      const toSave = pendingRef.current
      if (toSave === null) return
      pendingRef.current = null
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      timerRef.current = null
      lastSavedRef.current = toSave
      void saveSetupProgress(JSON.parse(toSave), { keepalive: true }).catch(() => undefined)
    }
    const onVisibility = () => { if (document.visibilityState === 'hidden') flush() }
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])
}
