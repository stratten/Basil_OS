// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryIntelligenceSettingsApp } from './MemoryIntelligenceSettingsApp'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(jsonResponse({ batches: [{ batch_id: 'import-1', imported_at: '2026-01-02T00:00:00+00:00', label: 'me.md', entry_count: 3 }] }))
  vi.stubGlobal('fetch', fetchMock)
  window.basilSettingsConfig = { apiBaseUrl: 'http://127.0.0.1:8123' }
  window.webkit = { messageHandlers: { basilMemoryIntelligenceSettingsBridge: { postMessage: vi.fn() } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  // The dialogs portal into the Basil window surface, as they do in the app, so they stay inside the container the tests query.
  container.className = 'basil-webkit-window-surface'
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
  delete window.basilSettingsConfig
})

describe('Personal Context import section', () => {
  it('sits above the pending proposals, uses the injected backend address, and lists past imports with Undo', async () => {
    await act(async () => {
      root.render(<MemoryIntelligenceSettingsApp />)
      await Promise.resolve()
    })
    act(() => {
      window.basilMemoryIntelligenceSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: { memoryAfterTaskEnabled: false, memoryDailyEnabled: false, memoryDailyTimeLocal: '03:00', memoryProcessingModel: null },
        proposals: [],
        documents: [],
        availableModels: [],
      })
    })
    await act(async () => { await Promise.resolve() })

    const headings = Array.from(container.querySelectorAll('h2')).map(heading => heading.textContent)
    expect(headings.indexOf('Import Personal Context')).toBeGreaterThanOrEqual(0)
    expect(headings.indexOf('Import Personal Context')).toBeLessThan(headings.indexOf('Pending Memory Proposals'))
    expect(container.textContent).toContain('Drop your personal info here if you have it available.')
    expect(headings).toContain('Build Your Profile From Existing Data')
    expect(headings.indexOf('Build Your Profile From Existing Data')).toBeGreaterThan(headings.indexOf('Import Personal Context'))
    expect(headings.indexOf('Build Your Profile From Existing Data')).toBeLessThan(headings.indexOf('Pending Memory Proposals'))
    expect(container.querySelectorAll('[data-testid="context-import-route-notice"]')).toHaveLength(2)
    expect(container.textContent).toContain('Basil reads this text with the Evaluator model above')
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8123/memory/context-import/batches', undefined)
    expect(container.textContent).toContain('me.md, 3 entries')
    expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Undo import')).toBe(true)
  })
})
