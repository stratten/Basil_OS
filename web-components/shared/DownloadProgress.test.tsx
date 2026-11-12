// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { DownloadProgress, wholePercent } from './DownloadProgress'
import { formatBytes } from './formatBytes'

let container: HTMLElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function render(props: Parameters<typeof DownloadProgress>[0]) {
  act(() => { root.render(<DownloadProgress {...props} />) })
}

const bar = () => container.querySelector<HTMLElement>('[role="progressbar"]')!
const fill = () => container.querySelector<HTMLElement>('.download-progress__fill')!
const amount = () => container.querySelector('.download-progress__amount')
const percent = () => container.querySelector('.download-progress__percent')!.textContent

describe('DownloadProgress', () => {
  it('shows the amount downloaded on the left of the data row and the percentage on the right', () => {
    render({ percent: 42.6, downloadedBytes: 2_400_000_000, totalBytes: 5_700_000_000, label: 'Qwen3.5-9B' })

    const row = container.querySelector('.download-progress__data')!
    expect(Array.from(row.children).map(child => child.className)).toEqual(['download-progress__amount', 'download-progress__percent'])
    expect(amount()!.textContent).toBe('2.4 GB / 5.7 GB')
    expect(percent()).toBe('42%')
  })

  it('exposes a labeled progress bar and fills the track to the exact percentage', () => {
    render({ percent: 42.6, label: 'Qwen3.5-9B' })

    expect(bar().getAttribute('aria-label')).toBe('Qwen3.5-9B')
    expect(bar().getAttribute('aria-valuemin')).toBe('0')
    expect(bar().getAttribute('aria-valuemax')).toBe('100')
    expect(bar().getAttribute('aria-valuenow')).toBe('42')
    expect(fill().style.width).toBe('42.6%')
  })

  it('shows only the percentage when the amount is not known', () => {
    render({ percent: 10, label: 'Model' })
    expect(amount()).toBeNull()
    expect(percent()).toBe('10%')
  })

  it('leaves the amount out when the total is zero, missing or null, or the downloaded amount is negative', () => {
    for (const props of [
      { downloadedBytes: 0, totalBytes: 0 },
      { downloadedBytes: 100, totalBytes: null },
      { downloadedBytes: null, totalBytes: 100 },
      { downloadedBytes: -5, totalBytes: 100 },
      { downloadedBytes: undefined, totalBytes: undefined },
    ]) {
      render({ percent: 5, label: 'Model', ...props })
      expect(amount()).toBeNull()
    }
  })

  it('clamps a percentage outside 0 to 100 and treats a non-number as zero', () => {
    render({ percent: 140, label: 'Model' })
    expect(percent()).toBe('100%')
    expect(fill().style.width).toBe('100%')

    render({ percent: -20, label: 'Model' })
    expect(percent()).toBe('0%')

    render({ percent: Number.NaN, label: 'Model' })
    expect(percent()).toBe('0%')
    expect(bar().getAttribute('aria-valuenow')).toBe('0')
  })

  it('adds a caller class next to its own', () => {
    render({ percent: 1, label: 'Model', className: 'extra' })
    expect(container.firstElementChild!.className).toBe('download-progress extra')
  })
})

describe('DownloadProgress waiting note', () => {
  const note = () => container.querySelector('.download-progress__note')
  const WAITING = 'Waiting for Hugging Face to start sending data (20s)...'

  it('shows the note while the bar is at zero and no bytes have arrived', () => {
    render({ percent: 0, downloadedBytes: 0, totalBytes: 2_740_000_000, label: 'Model', waitingNote: WAITING })

    expect(note()!.textContent).toBe(WAITING)
    expect(note()!.getAttribute('role')).toBe('status')
  })

  it('shows the note when the amount is not known at all', () => {
    render({ percent: 0, label: 'Model', waitingNote: WAITING })

    expect(note()!.textContent).toBe(WAITING)
  })

  it('hides the note as soon as any bytes have arrived, even if the whole percent is still zero', () => {
    render({ percent: 0.4, downloadedBytes: 11_000_000, totalBytes: 2_740_000_000, label: 'Model', waitingNote: WAITING })

    expect(note()).toBeNull()
  })

  it('hides the note once the bar has moved', () => {
    render({ percent: 3, label: 'Model', waitingNote: WAITING })

    expect(note()).toBeNull()
  })

  it('shows nothing for a missing, null, empty or blank note', () => {
    for (const waitingNote of [undefined, null, '', '   ']) {
      render({ percent: 0, label: 'Model', waitingNote })
      expect(note()).toBeNull()
    }
  })

  it('trims the note and removes it again when the next update carries none', () => {
    render({ percent: 0, label: 'Model', waitingNote: `  ${WAITING}  ` })
    expect(note()!.textContent).toBe(WAITING)

    render({ percent: 0, label: 'Model', waitingNote: null })
    expect(note()).toBeNull()
  })
})

describe('wholePercent', () => {
  it('rounds down, so a download never reads as finished early, and survives floating-point error', () => {
    expect(wholePercent(99.9)).toBe(99)
    expect(wholePercent(0.29 * 100)).toBe(29)
    expect(wholePercent(0.3 * 100)).toBe(30)
    expect(wholePercent(100)).toBe(100)
  })
})

describe('formatBytes', () => {
  it('writes byte counts in decimal units', () => {
    expect(formatBytes(0)).toBe('0 bytes')
    expect(formatBytes(400)).toBe('400 bytes')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(151_000_000)).toBe('151 MB')
    expect(formatBytes(5_680_000_000)).toBe('5.7 GB')
  })
})
