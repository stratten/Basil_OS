// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const api = vi.hoisted(() => ({ fetchExpressReceipt: vi.fn() }))
vi.mock('@/services/api', () => api)

import { SetupReceiptSection } from './SetupReceiptSection'

const RECEIPT = {
  items: [
    { id: 'download_thinking_model', group: 'downloads', title: 'Thinking model', state: 'on', detail: 'Qwen 3.5 9B is on this Mac.', where_to_change: 'Settings, Capabilities, Models' },
    { id: 'capture_activity', group: 'background', title: 'Activity Capture', state: 'partial', detail: 'In the Basil menu. You start it yourself.', where_to_change: 'Settings, General, Home' },
    { id: 'voice_listener', group: 'background', title: 'Voice Listener', state: 'off', detail: 'Off.', where_to_change: 'Settings, General, Home' },
  ],
}

let container: HTMLElement
let root: Root

async function render(refreshKey?: string) {
  await act(async () => {
    root.render(<SetupReceiptSection refreshKey={refreshKey} />)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  api.fetchExpressReceipt.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SetupReceiptSection', () => {
  it('lists every item with its state in words, its detail and where to change it', async () => {
    api.fetchExpressReceipt.mockResolvedValue(RECEIPT)

    await render()

    const rows = Array.from(container.querySelectorAll('.express-receipt-row'))
    expect(rows).toHaveLength(3)
    expect(rows[0].textContent).toContain('On')
    expect(rows[0].textContent).toContain('Qwen 3.5 9B is on this Mac.')
    expect(rows[0].textContent).toContain('Change it in Settings, Capabilities, Models.')
    expect(rows[1].textContent).toContain('Partly on')
    expect(rows[2].textContent).toContain('Off')
    expect(container.querySelector('h2')!.textContent).toBe("What's on right now")
  })

  it('renders nothing when the receipt cannot be read, rather than a stale list', async () => {
    api.fetchExpressReceipt.mockRejectedValue(new Error('down'))

    await render()

    expect(container.querySelector('.express-receipt')).toBeNull()
  })

  it('renders nothing for an empty receipt', async () => {
    api.fetchExpressReceipt.mockResolvedValue({ items: [] })

    await render()

    expect(container.querySelector('.express-receipt')).toBeNull()
  })

  it('reads the receipt again when its refresh key changes, and hides it if the second read fails', async () => {
    api.fetchExpressReceipt.mockResolvedValueOnce(RECEIPT).mockRejectedValueOnce(new Error('down'))

    await render('a')
    expect(container.querySelector('.express-receipt')).not.toBeNull()

    await render('b')

    expect(api.fetchExpressReceipt).toHaveBeenCalledTimes(2)
    expect(container.querySelector('.express-receipt')).toBeNull()
  })
})
