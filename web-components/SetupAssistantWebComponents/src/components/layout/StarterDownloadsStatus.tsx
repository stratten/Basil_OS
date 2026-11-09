import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchStarterDownloadProgress } from '@/services/api'

import { ModelDownloadRows } from './ModelDownloadRows'
import { useModelStarts } from './useModelStarts'
import {
  describeStarterDownloads,
  hasActiveStarterDownload,
  isStarterPackFinished,
  startableRows,
  type StarterDownloadRow,
} from './starterDownloads'

const ACTIVE_POLL_MS = 2000
const IDLE_POLL_MS = 6000

/**
 * The wrap-up screen's status for the three starter downloads: each model by name, with its state and a button to start or retry it.
 * It disappears once everything is ready, and it renders nothing if the status cannot be read.
 */
export function StarterDownloadsStatus() {
  const [rows, setRows] = useState<StarterDownloadRow[] | null>(null)
  const isMountedRef = useRef(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const refresh = useCallback(async () => {
    let nextRows: StarterDownloadRow[] | null = null
    try {
      nextRows = describeStarterDownloads(await fetchStarterDownloadProgress())
    } catch {
      nextRows = null
    }
    if (!isMountedRef.current) return
    setRows(nextRows)
    if (nextRows === null || isStarterPackFinished(nextRows)) return
    timerRef.current = setTimeout(() => { void refresh() }, hasActiveStarterDownload(nextRows) ? ACTIVE_POLL_MS : IDLE_POLL_MS)
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    void refresh()
    return () => {
      isMountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [refresh])

  const { startingIds, error, startRows } = useModelStarts(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    void refresh()
  })

  if (rows === null || isStarterPackFinished(rows)) return null

  return (
    <section className="starter-downloads" aria-label="Model downloads">
      <h2 className="starter-downloads__title">Model downloads</h2>
      <ModelDownloadRows
        rows={rows}
        startingIds={startingIds}
        error={error}
        onStart={(row, method) => { void startRows([row], method) }}
        onStartAll={method => { void startRows(startableRows(rows), method) }}
      />
    </section>
  )
}
