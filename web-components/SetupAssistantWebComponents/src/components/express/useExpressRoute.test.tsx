// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const api = vi.hoisted(() => ({
  fetchStarterDownloadProgress: vi.fn(),
  selectModelAccess: vi.fn(),
}))
vi.mock('@/services/api', () => api)

import { THINKING_MODEL_ID } from './expressTestSupport'
import {
  LOCAL_ACCESS_RESOLVED,
  LOCAL_ACCESS_UNRESOLVED,
  NO_MODELS,
  THINKING_COMPLETED,
  THINKING_DOWNLOADING,
  THINKING_FAILED,
  VOICE_DOWNLOADING,
  progressWith,
} from './expressProgressFixtures'
import {
  FAILED_DOWNLOAD_MESSAGE,
  MISSING_ROW_MESSAGE,
  NO_THINKING_MODEL_MESSAGE,
  UNRESOLVED_ROUTE_MESSAGE,
  useExpressRoute,
} from './useExpressRoute'

let container: HTMLElement
let root: Root
const onSelect = vi.fn()

function Probe({ thinkingModelId }: { thinkingModelId: string | null }) {
  const route = useExpressRoute({ thinkingModelId, onSelectModelAccess: onSelect })
  return <div id="probe" data-state={route.state} data-message={route.message ?? ''} data-rows={route.rows.length} />
}

function probe() {
  return container.querySelector<HTMLElement>('#probe')!
}

async function mount(thinkingModelId: string | null = THINKING_MODEL_ID) {
  await act(async () => {
    root.render(<Probe thinkingModelId={thinkingModelId} />)
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  api.fetchStarterDownloadProgress.mockReset()
  api.selectModelAccess.mockReset()
  onSelect.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('useExpressRoute', () => {
  it('waits while the thinking model downloads, then confirms the local route once and stops polling', async () => {
    api.fetchStarterDownloadProgress
      .mockResolvedValueOnce(THINKING_DOWNLOADING)
      .mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    expect(probe().dataset.state).toBe('waiting')
    expect(api.selectModelAccess).not.toHaveBeenCalled()

    await advance(2000)

    expect(api.selectModelAccess).toHaveBeenCalledTimes(1)
    expect(api.selectModelAccess).toHaveBeenCalledWith({ mode: 'local', local_model_id: THINKING_MODEL_ID })
    expect(onSelect).toHaveBeenCalledWith(LOCAL_ACCESS_RESOLVED.access)
    expect(probe().dataset.state).toBe('ready')

    const reads = api.fetchStarterDownloadProgress.mock.calls.length
    await advance(20000)
    expect(api.fetchStarterDownloadProgress).toHaveBeenCalledTimes(reads)
    expect(api.selectModelAccess).toHaveBeenCalledTimes(1)
  })

  it('is ready on the first read when the model is already installed', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()

    expect(probe().dataset.state).toBe('ready')
    expect(api.fetchStarterDownloadProgress).toHaveBeenCalledTimes(1)
  })

  it('confirms the route only once while another download keeps the poll running', async () => {
    const both = progressWith({ ...THINKING_COMPLETED.models, ...VOICE_DOWNLOADING })
    api.fetchStarterDownloadProgress.mockResolvedValue(both)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    await advance(6000)

    expect(api.fetchStarterDownloadProgress.mock.calls.length).toBeGreaterThan(2)
    expect(api.selectModelAccess).toHaveBeenCalledTimes(1)
    expect(probe().dataset.rows).toBe('2')
  })

  it('asks for the manual choice when the thinking download fails', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_FAILED)

    await mount()

    expect(probe().dataset.state).toBe('needs_manual')
    expect(probe().dataset.message).toBe(FAILED_DOWNLOAD_MESSAGE)
    expect(api.selectModelAccess).not.toHaveBeenCalled()
  })

  it('recovers after a retry: a later poll that sees the model complete becomes ready', async () => {
    api.fetchStarterDownloadProgress
      .mockResolvedValueOnce(THINKING_FAILED)
      .mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    expect(probe().dataset.state).toBe('needs_manual')

    await advance(2000)

    expect(probe().dataset.state).toBe('ready')
    expect(probe().dataset.message).toBe('')
  })

  it('asks for the manual choice when the thinking row is missing from the progress', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(NO_MODELS)

    await mount()

    expect(probe().dataset.state).toBe('needs_manual')
    expect(probe().dataset.message).toBe(MISSING_ROW_MESSAGE)
  })

  it('keeps waiting and tries again when a progress read fails', async () => {
    api.fetchStarterDownloadProgress
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_RESOLVED)

    await mount()
    expect(probe().dataset.state).toBe('waiting')
    expect(probe().dataset.rows).toBe('0')

    await advance(2000)

    expect(probe().dataset.state).toBe('ready')
  })

  it('asks for the manual choice when the local route does not resolve', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockResolvedValue(LOCAL_ACCESS_UNRESOLVED)

    await mount()

    expect(onSelect).toHaveBeenCalledWith(LOCAL_ACCESS_UNRESOLVED.access)
    expect(probe().dataset.state).toBe('needs_manual')
    expect(probe().dataset.message).toBe(UNRESOLVED_ROUTE_MESSAGE)
  })

  it('shows the error message when selecting the route fails', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_COMPLETED)
    api.selectModelAccess.mockRejectedValue(new Error('The model is not installed yet.'))

    await mount()

    expect(onSelect).not.toHaveBeenCalled()
    expect(probe().dataset.state).toBe('needs_manual')
    expect(probe().dataset.message).toBe('The model is not installed yet.')
  })

  it('goes straight to the manual choice when there is no thinking model to wait for', async () => {
    await mount(null)

    expect(probe().dataset.state).toBe('needs_manual')
    expect(probe().dataset.message).toBe(NO_THINKING_MODEL_MESSAGE)
    expect(api.fetchStarterDownloadProgress).not.toHaveBeenCalled()
  })

  it('stops polling when it unmounts', async () => {
    api.fetchStarterDownloadProgress.mockResolvedValue(THINKING_DOWNLOADING)

    await mount()
    const reads = api.fetchStarterDownloadProgress.mock.calls.length

    act(() => { root.unmount() })
    root = createRoot(container)
    await advance(10000)

    expect(api.fetchStarterDownloadProgress).toHaveBeenCalledTimes(reads)
  })
})
