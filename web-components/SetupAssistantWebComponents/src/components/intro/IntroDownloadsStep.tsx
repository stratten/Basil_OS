import { useCallback, useEffect, useRef, useState } from 'react'

import { ModelDownloadRows } from '@/components/layout/ModelDownloadRows'
import {
  describeStarterDownloads,
  hasActiveStarterDownload,
  isStarterPackFinished,
  reasoningRowFromOption,
  reportedBytes,
  startableRows,
  type LiveLocalDownload,
  type StarterDownloadRow,
} from '@/components/layout/starterDownloads'
import { useModelStarts } from '@/components/layout/useModelStarts'
import { fetchLocalModelDownloadProgress, fetchModelAccessOptions, fetchStarterDownloadProgress } from '@/services/api'
import type { SetupAgentModelAccessOption } from '@/types'

import { LocalModelChooser } from './LocalModelChooser'

const ACTIVE_POLL_MS = 2000
const IDLE_POLL_MS = 6000

type LoadState = 'loading' | 'ready' | 'unavailable'

interface Snapshot {
  voiceRows: StarterDownloadRow[]
  localOption: SetupAgentModelAccessOption | undefined
  live: LiveLocalDownload | null
}

interface Props {
  /** The local reasoning model a validation build's tester picked, or null for the machine's default. */
  chosenLocalModelId: string | null
  onChosenLocalModelIdChange: (modelId: string) => void
}

/** The three starter models by name (two voice models and the thinking model), each with its own Download button and one Download all below them. Continuing without downloading is fine; the model step still offers the thinking model's download. */
export function IntroDownloadsStep({ chosenLocalModelId, onChosenLocalModelIdChange }: Props) {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [snapshot, setSnapshot] = useState<Snapshot>({ voiceRows: [], localOption: undefined, live: null })
  const isMountedRef = useRef(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestSequenceRef = useRef(0)
  const chosenRef = useRef(chosenLocalModelId)
  chosenRef.current = chosenLocalModelId

  const refresh = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const sequence = ++requestSequenceRef.current
    const [starterResult, accessResult] = await Promise.allSettled([
      fetchStarterDownloadProgress(),
      fetchModelAccessOptions(false, chosenRef.current),
    ])
    if (!isMountedRef.current || sequence !== requestSequenceRef.current) return

    let voiceRows: StarterDownloadRow[] = []
    if (starterResult.status === 'fulfilled') {
      try {
        voiceRows = describeStarterDownloads(starterResult.value).filter(row => row.isVoiceModel)
      } catch {
        voiceRows = []
      }
    }
    const localOption = accessResult.status === 'fulfilled'
      ? accessResult.value.options.find(option => option.mode === 'local')
      : undefined

    let live: Snapshot['live'] = null
    if (localOption?.downloaded === false && localOption.local_model_type && localOption.local_model_variant) {
      try {
        const progress = await fetchLocalModelDownloadProgress(localOption.local_model_type, localOption.local_model_variant)
        live = {
          status: progress.status,
          percent: (progress.progress ?? 0) * 100,
          downloadedBytes: reportedBytes(progress.total_downloaded),
          totalBytes: reportedBytes(progress.total_size),
        }
      } catch {
        live = null
      }
      if (!isMountedRef.current || sequence !== requestSequenceRef.current) return
    }

    const rows = [...voiceRows, reasoningRowFromOption(localOption, live)].filter((row): row is StarterDownloadRow => row !== null)
    if (rows.length === 0) {
      setLoadState('unavailable')
      return
    }
    setSnapshot({ voiceRows, localOption, live })
    setLoadState('ready')
    if (isStarterPackFinished(rows)) return
    timerRef.current = setTimeout(() => { void refresh() }, hasActiveStarterDownload(rows) ? ACTIVE_POLL_MS : IDLE_POLL_MS)
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh, chosenLocalModelId])

  const { startingIds, error, startRows } = useModelStarts(() => { void refresh() })

  const reasoningRow = reasoningRowFromOption(snapshot.localOption, snapshot.live)
  const rows = [...snapshot.voiceRows, reasoningRow].filter((row): row is StarterDownloadRow => row !== null)
  const isFinished = isStarterPackFinished(rows)

  return (
    <div className="intro-step-body">
      <h3>Model downloads</h3>
      <p className="intro-step-lede">
        Basil uses models that run on this Mac: two to hear you and one to think. Download them now so they are ready, or skip this and download them later. The next step can also download the thinking model. You can download or change any of them later in Settings, Models.
      </p>

      {loadState === 'loading' && <p role="status">Checking which models are on this Mac…</p>}
      {loadState === 'unavailable' && (
        <p className="model-downloads__error" role="alert">
          I couldn’t reach the setup service to read the model downloads. You can still continue.
        </p>
      )}
      {loadState === 'ready' && (
        <>
          <LocalModelChooser
            choices={snapshot.localOption?.local_model_choices ?? []}
            value={snapshot.localOption?.local_model_id ?? null}
            onChange={onChosenLocalModelIdChange}
          />
          <ModelDownloadRows
            rows={rows}
            startingIds={startingIds}
            error={error}
            onStart={(row, method) => { void startRows([row], method) }}
            onStartAll={method => { void startRows(startableRows(rows), method) }}
          />
          {isFinished && <p role="status" className="intro-downloads-ready">Every model is ready on this Mac.</p>}
        </>
      )}
    </div>
  )
}
