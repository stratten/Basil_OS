// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { formatMemory, ModelComparison } from './ModelComparison'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

async function renderComparison() {
  await act(async () => {
    root.render(<ModelComparison />)
    await Promise.resolve()
  })
  await act(async () => { await Promise.resolve() })
}

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('ModelComparison', () => {
  it('lists the two fixed routes and the registry local models with their ratings and memory', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      recommendations: [
        { modelId: 'a', displayName: 'Qwen 4B', size: '2.5 GB', speedRating: 8, accuracyRating: 6, recommendedRam: '8GB', systemCompatible: true },
        { modelId: 'b', displayName: 'Big 70B', size: '40 GB', speedRating: 2, accuracyRating: 9, recommendedRam: '64GB', systemCompatible: false },
      ],
      systemInfo: { totalRamGB: 16 },
    }))

    await renderComparison()

    expect(fetchMock).toHaveBeenCalledWith('/models/recommendations', expect.objectContaining({ method: 'POST' }))
    const rows = Array.from(container.querySelectorAll('tbody tr')).map(row => row.textContent ?? '')
    expect(rows).toHaveLength(4)
    expect(rows[0]).toContain('Basil Cloud')
    expect(rows[1]).toContain('Your own API key')
    expect(rows[2]).toContain('Qwen 4B')
    expect(rows[2]).toContain('8 out of 10')
    expect(rows[2]).toContain('8GB or more')
    expect(rows[3]).toContain('may be too large for this Mac')
    expect(container.textContent).toContain('This Mac has 16 GB of memory')
  })

  it('still shows the two fixed routes and says so when the local list cannot be read', async () => {
    fetchMock.mockRejectedValue(new Error('offline'))

    await renderComparison()

    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(container.querySelector('[role="status"]')?.textContent).toContain('could not read the local model list')
  })

  it('says a model lists no memory requirement instead of printing an empty cell', () => {
    expect(formatMemory('')).toBe('Not listed')
    expect(formatMemory(' 16GB ')).toBe('16GB or more')
  })
})
