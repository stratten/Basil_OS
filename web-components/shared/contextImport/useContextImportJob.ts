import { useCallback, useEffect, useRef, useState } from 'react'

import type { ContextImportClient, ImportJobStart, ImportStage } from './contextImportClient'

export const JOB_POLL_INTERVAL_MS = 800
const MAX_CONSECUTIVE_POLL_FAILURES = 3

export type JobPhase = 'idle' | 'starting' | 'running' | 'done' | 'failed' | 'canceled'

export interface JobView<Result> {
  phase: JobPhase
  message: string
  done: number
  total: number
  stage: ImportStage
  tokensWritten: number
  thinking: string
  result: Result | null
  error: string | null
}

const IDLE_VIEW: JobView<never> = { phase: 'idle', message: '', done: 0, total: 0, stage: 'loading', tokensWritten: 0, thinking: '', result: null, error: null }

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/** Starts one import job and follows it to the end by polling, so a page never waits on a single long request. Polling stops on unmount and on reset. */
export function useContextImportJob<Result>(client: ContextImportClient) {
  const [view, setView] = useState<JobView<Result>>(IDLE_VIEW)
  const jobIdRef = useRef<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Each start takes a new generation, so a poll that was already in flight when the job was reset or replaced cannot write stale state.
  const generationRef = useRef(0)

  const stopPolling = useCallback(() => {
    generationRef.current += 1
    if (timerRef.current !== null) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  // The cleanup reads the client through a ref, so a parent that hands over a new client object mid-read does not cancel the job by accident.
  const clientRef = useRef(client)
  clientRef.current = client

  // Leaving the page abandons the import: polling stops and a job that is still reading is canceled, so it cannot block the next import.
  useEffect(() => () => {
    stopPolling()
    const jobId = jobIdRef.current
    if (jobId) void clientRef.current.cancelJob(jobId).catch(() => undefined)
  }, [stopPolling])

  const poll: (jobId: string, generation: number, failures: number) => void = useCallback((jobId: string, generation: number, failures: number) => {
    timerRef.current = setTimeout(async () => {
      if (generation !== generationRef.current) return
      try {
        const status = await client.readJob<Result>(jobId)
        if (generation !== generationRef.current) return
        if (status.state === 'running') {
          setView({ phase: 'running', message: status.message, done: status.chunks_done, total: status.chunks_total, stage: status.stage ?? 'reading', tokensWritten: status.tokens_written ?? 0, thinking: status.thinking ?? '', result: null, error: null })
          poll(jobId, generation, 0)
          return
        }
        jobIdRef.current = null
        setView({ phase: status.state, message: status.message, done: status.chunks_done, total: status.chunks_total, stage: status.stage ?? 'reading', tokensWritten: status.tokens_written ?? 0, thinking: status.thinking ?? '', result: status.result, error: status.error })
      } catch (error) {
        if (generation !== generationRef.current) return
        if (failures + 1 >= MAX_CONSECUTIVE_POLL_FAILURES) {
          jobIdRef.current = null
          setView({ ...IDLE_VIEW, phase: 'failed', error: errorText(error, 'Basil lost track of the import. Nothing was saved. Try again.') })
          return
        }
        poll(jobId, generation, failures + 1)
      }
    }, JOB_POLL_INTERVAL_MS)
  }, [client])

  const start = useCallback(async (begin: () => Promise<ImportJobStart>) => {
    stopPolling()
    const generation = generationRef.current
    setView({ ...IDLE_VIEW, phase: 'starting', message: 'Starting.' })
    try {
      const started = await begin()
      if (generation !== generationRef.current) return
      jobIdRef.current = started.job_id
      setView({ phase: 'running', message: 'Starting.', done: 0, total: started.chunks_total, stage: 'loading', tokensWritten: 0, thinking: '', result: null, error: null })
      poll(started.job_id, generation, 0)
    } catch (error) {
      if (generation !== generationRef.current) return
      setView({ ...IDLE_VIEW, phase: 'failed', error: errorText(error, 'The import could not be started.') })
    }
  }, [poll, stopPolling])

  const cancel = useCallback(async () => {
    const jobId = jobIdRef.current
    if (!jobId) return
    setView(current => ({ ...current, message: 'Stopping.' }))
    try {
      await client.cancelJob(jobId)
    } catch {
      // The next poll reports whatever state the job is really in, so a failed cancel request needs no message of its own.
    }
  }, [client])

  const reset = useCallback(() => {
    stopPolling()
    jobIdRef.current = null
    setView(IDLE_VIEW)
  }, [stopPolling])

  return { view, start, cancel, reset }
}
