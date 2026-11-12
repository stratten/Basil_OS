import { useCallback, useEffect, useRef, useState } from 'react'

import {
  describeStarterDownloads,
  hasActiveStarterDownload,
  type StarterDownloadRow,
} from '@/components/layout/starterDownloads'
import { fetchStarterDownloadProgress, selectModelAccess } from '@/services/api'
import type { SetupAgentModelAccess } from '@/types'

const POLL_MS = 2000

export type ExpressRouteState = 'waiting' | 'selecting' | 'ready' | 'needs_manual'

export const NO_THINKING_MODEL_MESSAGE = "I'm not setting up a thinking model here, so you'll choose how I think on the next screen."
export const FAILED_DOWNLOAD_MESSAGE = "The thinking model didn't download. You can try again here, or choose another way for me to think."
export const UNRESOLVED_ROUTE_MESSAGE = "I couldn't confirm the local model as how I think. You can choose that yourself on the next screen."
export const MISSING_ROW_MESSAGE = "I can't see the thinking model's download. You can choose how I think on the next screen."

type Confirmation =
  | { kind: 'idle' }
  | { kind: 'selecting' }
  | { kind: 'ready' }
  | { kind: 'unresolved', message: string }

interface Options {
  /** The canonical registry id the apply step returned, or null when there is no thinking model to wait for. */
  thinkingModelId: string | null
  onSelectModelAccess: (access: SetupAgentModelAccess) => void
}

export function useExpressRoute({ thinkingModelId, onSelectModelAccess }: Options) {
  const [rows, setRows] = useState<StarterDownloadRow[]>([])
  const [hasLoaded, setHasLoaded] = useState(false)
  const [confirmation, setConfirmation] = useState<Confirmation>({ kind: 'idle' })
  const [pollNonce, setPollNonce] = useState(0)
  const attemptedRef = useRef(false)
  const isMountedRef = useRef(true)
  const onSelectRef = useRef(onSelectModelAccess)
  onSelectRef.current = onSelectModelAccess

  useEffect(() => {
    isMountedRef.current = true
    return () => { isMountedRef.current = false }
  }, [])

  const confirmRoute = useCallback(async (modelId: string) => {
    setConfirmation({ kind: 'selecting' })
    try {
      const response = await selectModelAccess({ mode: 'local', local_model_id: modelId })
      if (!isMountedRef.current) return
      onSelectRef.current(response.access)
      setConfirmation(
        response.access.resolved
          ? { kind: 'ready' }
          : { kind: 'unresolved', message: UNRESOLVED_ROUTE_MESSAGE },
      )
    } catch (error) {
      if (!isMountedRef.current) return
      setConfirmation({
        kind: 'unresolved',
        message: error instanceof Error && error.message ? error.message : UNRESOLVED_ROUTE_MESSAGE,
      })
    }
  }, [])

  useEffect(() => {
    if (!thinkingModelId) return undefined
    let canceled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const tick = async () => {
      let next: StarterDownloadRow[] | null = null
      try {
        next = describeStarterDownloads(await fetchStarterDownloadProgress())
      } catch {
        next = null
      }
      if (canceled) return
      if (next) {
        setRows(next)
        setHasLoaded(true)
        const thinking = next.find(row => row.id === thinkingModelId)
        if (thinking?.state === 'completed' && !attemptedRef.current) {
          attemptedRef.current = true
          void confirmRoute(thinkingModelId)
        }
      }
      const keepPolling = next === null || hasActiveStarterDownload(next) || !attemptedRef.current
      if (keepPolling) timer = setTimeout(() => { void tick() }, POLL_MS)
    }

    void tick()
    return () => {
      canceled = true
      if (timer) clearTimeout(timer)
    }
  }, [thinkingModelId, confirmRoute, pollNonce])

  const refreshNow = useCallback(() => setPollNonce(value => value + 1), [])

  const thinkingRow = thinkingModelId ? rows.find(row => row.id === thinkingModelId) ?? null : null
  let state: ExpressRouteState
  let message: string | null = null
  if (!thinkingModelId) {
    state = 'needs_manual'
    message = NO_THINKING_MODEL_MESSAGE
  } else if (confirmation.kind === 'ready') {
    state = 'ready'
  } else if (confirmation.kind === 'selecting') {
    state = 'selecting'
  } else if (confirmation.kind === 'unresolved') {
    state = 'needs_manual'
    message = confirmation.message
  } else if (thinkingRow?.state === 'failed') {
    state = 'needs_manual'
    message = FAILED_DOWNLOAD_MESSAGE
  } else if (hasLoaded && thinkingRow === null) {
    state = 'needs_manual'
    message = MISSING_ROW_MESSAGE
  } else {
    state = 'waiting'
  }

  return { rows, state, message, refreshNow }
}
