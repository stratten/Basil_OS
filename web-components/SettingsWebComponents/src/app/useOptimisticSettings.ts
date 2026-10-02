import { useCallback, useRef, useState } from 'react'

export type SettingsIntentOutcome = 'unmatched' | 'success' | 'error'

export interface OptimisticSettings<T extends object> {
  settings: T | null
  isSaving: boolean
  setSettings: (next: T) => void
  track: (requestId: string) => void
  receiveSnapshot: (snapshot: T | null) => void
  resolveIntent: (requestId: string, status: string) => SettingsIntentOutcome
}

function changedFields<T extends object>(current: T, next: T): Partial<T> {
  const patch: Partial<T> = {}
  for (const key of Object.keys(next) as (keyof T)[]) {
    if (!Object.is(current[key], next[key])) patch[key] = next[key]
  }
  return patch
}

// Instant-save Settings surfaces stay interactive while native confirms each change: pending fields survive unrelated snapshots, and a failed field reverts to the last confirmed value.
export function useOptimisticSettings<T extends object>(): OptimisticSettings<T> {
  const [settings, setSettingsState] = useState<T | null>(null)
  const [pendingCount, setPendingCount] = useState(0)
  const settingsRef = useRef<T | null>(null)
  const confirmedRef = useRef<T | null>(null)
  const unsentPatchRef = useRef<Partial<T>>({})
  const pendingPatchesRef = useRef(new Map<string, Partial<T>>())

  const commit = useCallback((next: T | null) => {
    settingsRef.current = next
    setSettingsState(next)
  }, [])

  const setSettings = useCallback((next: T) => {
    const current = settingsRef.current
    if (current) unsentPatchRef.current = { ...unsentPatchRef.current, ...changedFields(current, next) }
    commit(next)
  }, [commit])

  const track = useCallback((requestId: string) => {
    pendingPatchesRef.current.set(requestId, unsentPatchRef.current)
    unsentPatchRef.current = {}
    setPendingCount(pendingPatchesRef.current.size)
  }, [])

  const receiveSnapshot = useCallback((snapshot: T | null) => {
    confirmedRef.current = snapshot
    if (!snapshot) {
      commit(null)
      return
    }
    let next = snapshot
    for (const patch of pendingPatchesRef.current.values()) next = { ...next, ...patch }
    commit(next)
  }, [commit])

  const resolveIntent = useCallback((requestId: string, status: string): SettingsIntentOutcome => {
    const patch = pendingPatchesRef.current.get(requestId)
    if (!patch) return 'unmatched'
    pendingPatchesRef.current.delete(requestId)
    setPendingCount(pendingPatchesRef.current.size)
    const confirmed = confirmedRef.current
    if (status !== 'error') {
      if (confirmed) confirmedRef.current = { ...confirmed, ...patch }
      return 'success'
    }
    const current = settingsRef.current
    if (confirmed && current) {
      const stillPendingKeys = new Set<keyof T>()
      for (const pendingPatch of pendingPatchesRef.current.values()) {
        for (const key of Object.keys(pendingPatch) as (keyof T)[]) stillPendingKeys.add(key)
      }
      const restored: Partial<T> = {}
      for (const key of Object.keys(patch) as (keyof T)[]) {
        if (!stillPendingKeys.has(key)) restored[key] = confirmed[key]
      }
      commit({ ...current, ...restored })
    }
    return 'error'
  }, [commit])

  return { settings, isSaving: pendingCount > 0, setSettings, track, receiveSnapshot, resolveIntent }
}
