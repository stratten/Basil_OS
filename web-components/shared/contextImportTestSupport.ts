import { act } from 'react'
import { vi } from 'vitest'

import type { ContextImportClient, ImportJobStatus } from './contextImportClient'
import { JOB_POLL_INTERVAL_MS } from './useContextImportJob'

export function makeClient(overrides: Partial<ContextImportClient> = {}): ContextImportClient {
  return {
    readImages: vi.fn().mockResolvedValue({ text: 'Text from a screenshot.' }),
    startRecordsJob: vi.fn().mockResolvedValue({ job_id: 'job-1', chunks_total: 2 }),
    startProfileJob: vi.fn().mockResolvedValue({ job_id: 'job-1', chunks_total: 2 }),
    readJob: vi.fn(),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    commit: vi.fn(),
    commitProfile: vi.fn(),
    undoProfile: vi.fn(),
    listBatches: vi.fn().mockResolvedValue([]),
    undo: vi.fn().mockResolvedValue({ entries_removed: 0 }),
    ...overrides,
  }
}

export function jobStatus<Result>(overrides: Partial<ImportJobStatus<Result>> = {}): ImportJobStatus<Result> {
  return {
    job_id: 'job-1',
    kind: 'records',
    label: '',
    state: 'running',
    chunks_done: 0,
    chunks_total: 2,
    message: 'Starting.',
    result: null,
    error: null,
    ...overrides,
  }
}

/** Moves fake timers forward by whole poll intervals, letting each poll's promises settle. Requires `vi.useFakeTimers()`. */
export async function advancePolls(count = 1) {
  for (let index = 0; index < count; index += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS)
    })
  }
}

export function typeInto(container: HTMLElement, selector: string, value: string) {
  const textarea = container.querySelector<HTMLTextAreaElement>(selector)!
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  act(() => {
    setValue.call(textarea, value)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

export async function clickIn(container: HTMLElement, selector: string) {
  await act(async () => {
    container.querySelector<HTMLElement>(selector)!.click()
    await Promise.resolve()
    await Promise.resolve()
  })
}

export async function chooseFileIn(container: HTMLElement, file: File) {
  const input = container.querySelector<HTMLInputElement>('.context-import-file')!
  await act(async () => {
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    input.dispatchEvent(new Event('change', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 0))
  })
}
