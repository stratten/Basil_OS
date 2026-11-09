import { useCallback, useEffect, useRef, useState } from 'react'

import { copyLocalModelFromNormalBasil, startLocalModelDownload } from '@/services/api'

import type { ModelStartMethod } from './ModelDownloadRows'
import type { StarterDownloadRow } from './starterDownloads'

/**
 * Starts model downloads (or, in a validation build, copies from the normal Basil) for the rows it is given, one after another.
 * It tracks which rows have a start request in flight and the first failure message, and calls `onStarted` once every request has been answered so the caller can re-read progress.
 */
export function useModelStarts(onStarted: () => void) {
  const [startingIds, setStartingIds] = useState<ReadonlySet<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const isMountedRef = useRef(true)
  const onStartedRef = useRef(onStarted)
  onStartedRef.current = onStarted

  useEffect(() => {
    isMountedRef.current = true
    return () => { isMountedRef.current = false }
  }, [])

  const startRows = useCallback(async (rows: StarterDownloadRow[], method: ModelStartMethod) => {
    const startable = rows.filter(row => row.modelType && row.variant && (method === 'download' || row.canCopy))
    if (startable.length === 0) return
    setStartingIds(new Set(startable.map(row => row.id)))
    setError(null)
    const failures: string[] = []
    for (const row of startable) {
      try {
        if (method === 'copy') await copyLocalModelFromNormalBasil(row.modelType, row.variant)
        else await startLocalModelDownload(row.modelType, row.variant)
      } catch (caught) {
        failures.push(caught instanceof Error ? caught.message : `Could not start ${row.title}.`)
      }
    }
    if (!isMountedRef.current) return
    setStartingIds(new Set())
    if (failures.length > 0) setError(failures[0])
    onStartedRef.current()
  }, [])

  return { startingIds, error, startRows }
}
