// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { ContextImportClient } from './contextImportClient'
import { advancePolls, jobStatus, makeClient } from './contextImportTestSupport'
import { useContextImportJob } from './useContextImportJob'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

function Harness({ client }: { client: ContextImportClient }) {
  const { view, start, cancel, reset } = useContextImportJob<{ ok: boolean }>(client)
  return (
    <div>
      <span data-testid="phase">{view.phase}</span>
      <span data-testid="message">{view.message}</span>
      <span data-testid="progress">{view.done}/{view.total}</span>
      <span data-testid="activity">{view.stage}:{view.tokensWritten}</span>
      <span data-testid="thinking">{view.thinking}</span>
      <span data-testid="error">{view.error ?? ''}</span>
      <span data-testid="result">{view.result ? JSON.stringify(view.result) : ''}</span>
      <button data-testid="start" onClick={() => { void start(() => client.startRecordsJob('t', 'f', 'l')) }} />
      <button data-testid="cancel" onClick={() => { void cancel() }} />
      <button data-testid="reset" onClick={reset} />
    </div>
  )
}

const text = (id: string) => container.querySelector(`[data-testid="${id}"]`)!.textContent

async function press(id: string) {
  await act(async () => {
    container.querySelector<HTMLElement>(`[data-testid="${id}"]`)!.click()
    await Promise.resolve()
    await Promise.resolve()
  })
}

async function mount(client: ContextImportClient) {
  await act(async () => { root.render(<Harness client={client} />) })
}

beforeEach(() => {
  vi.useFakeTimers()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('useContextImportJob', () => {
  it('follows a job from running to done by polling, then stops polling', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ chunks_done: 1, message: 'Read part 1 of 2.' }))
      .mockResolvedValueOnce(jobStatus({ state: 'done', chunks_done: 2, message: 'Finished.', result: { ok: true } }))
    const client = makeClient({ readJob })
    await mount(client)

    await press('start')
    expect(text('phase')).toBe('running')
    expect(text('progress')).toBe('0/2')

    await advancePolls(1)
    expect(text('message')).toBe('Read part 1 of 2.')
    expect(text('progress')).toBe('1/2')

    await advancePolls(1)
    expect(text('phase')).toBe('done')
    expect(text('result')).toBe('{"ok":true}')

    await advancePolls(3)
    expect(readJob).toHaveBeenCalledTimes(2)
  })

  it('reports a job that could not be started with the backend message', async () => {
    const client = makeClient({ startRecordsJob: vi.fn().mockRejectedValue(new Error('Another import is still reading.')) })
    await mount(client)

    await press('start')

    expect(text('phase')).toBe('failed')
    expect(text('error')).toBe('Another import is still reading.')
    await advancePolls(2)
    expect(client.readJob).not.toHaveBeenCalled()
  })

  it('shows a failed job with its plain message', async () => {
    const readJob = vi.fn().mockResolvedValueOnce(jobStatus({ state: 'failed', message: 'x', error: 'The model stopped giving readable answers.' }))
    await mount(makeClient({ readJob }))

    await press('start')
    await advancePolls(1)

    expect(text('phase')).toBe('failed')
    expect(text('error')).toBe('The model stopped giving readable answers.')
  })

  it('recovers from one failed poll but gives up after three in a row', async () => {
    const recovering = vi.fn()
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce(jobStatus({ state: 'done', result: { ok: true } }))
    await mount(makeClient({ readJob: recovering }))
    await press('start')
    await advancePolls(2)
    expect(text('phase')).toBe('done')

    const failing = vi.fn().mockRejectedValue(new Error('This import is no longer available. Start it again.'))
    await mount(makeClient({ readJob: failing }))
    await press('reset')
    await press('start')
    await advancePolls(3)

    expect(failing).toHaveBeenCalledTimes(3)
    expect(text('phase')).toBe('failed')
    expect(text('error')).toBe('This import is no longer available. Start it again.')
  })

  it('cancels the running job, shows Stopping, and then the canceled state the backend reports', async () => {
    const readJob = vi.fn().mockResolvedValueOnce(jobStatus({ state: 'canceled', message: 'Canceled. Nothing was saved.' }))
    const client = makeClient({ readJob })
    await mount(client)
    await press('start')

    await press('cancel')

    expect(client.cancelJob).toHaveBeenCalledWith('job-1')
    expect(text('message')).toBe('Stopping.')
    await advancePolls(1)
    expect(text('phase')).toBe('canceled')
    expect(text('message')).toBe('Canceled. Nothing was saved.')
  })

  it('cancels a job that is still reading when the page is left, and stops polling', async () => {
    const readJob = vi.fn()
    const client = makeClient({ readJob })
    await mount(client)
    await press('start')

    act(() => { root.unmount() })
    root = createRoot(container)

    expect(client.cancelJob).toHaveBeenCalledWith('job-1')
    await advancePolls(3)
    expect(readJob).not.toHaveBeenCalled()
  })

  it('does not send a cancel on unmount when nothing is running', async () => {
    const client = makeClient()
    await mount(client)

    act(() => { root.unmount() })
    root = createRoot(container)

    expect(client.cancelJob).not.toHaveBeenCalled()
  })

  it('reset stops polling and returns to idle', async () => {
    const readJob = vi.fn().mockResolvedValue(jobStatus({}))
    await mount(makeClient({ readJob }))
    await press('start')

    await press('reset')
    await advancePolls(3)

    expect(text('phase')).toBe('idle')
    expect(readJob).not.toHaveBeenCalled()
  })

  it('passes the stage and the words written so far through, and starts in the loading stage', async () => {
    const readJob = vi.fn().mockResolvedValue(jobStatus({ stage: 'reading', tokens_written: 640, chunks_done: 1, message: 'Read part 1 of 2.' }))
    await mount(makeClient({ readJob }))

    await press('start')
    expect(text('activity')).toBe('loading:0')

    await advancePolls(1)
    expect(text('activity')).toBe('reading:640')
  })

  it('passes the thinking text through, and has none before the first poll or from an older backend', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ stage: 'reading', thinking: 'Reading the date style.' }))
      .mockResolvedValueOnce(jobStatus({ stage: 'reading' }))
    await mount(makeClient({ readJob }))

    await press('start')
    expect(text('thinking')).toBe('')

    await advancePolls(1)
    expect(text('thinking')).toBe('Reading the date style.')

    await advancePolls(1)
    expect(text('thinking')).toBe('')
  })

  it('treats a backend that reports neither as reading with nothing written', async () => {
    const readJob = vi.fn().mockResolvedValue(jobStatus({ chunks_done: 1, message: 'Read part 1 of 2.' }))
    await mount(makeClient({ readJob }))

    await press('start')
    await advancePolls(1)

    expect(text('activity')).toBe('reading:0')
  })
})
