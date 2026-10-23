// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { nextRevealBoundary, usePacedText } from './usePacedText'

interface HarnessProps {
  messageId: string
  content: string
  progressive?: boolean
  streaming?: boolean
  hold?: boolean
}

function Harness({ messageId, content, progressive = true, streaming = false, hold = false }: HarnessProps) {
  const text = usePacedText({ messageId, content, progressive, streaming, hold })
  return <p data-testid="paced">{text}</p>
}

const LONG_TEXT = 'Basil can take notes during meetings and draft follow ups for you afterwards.'

let container: HTMLElement
let root: Root
let frameQueue: FrameRequestCallback[] = []
let frameClock = 0

function render(props: HarnessProps) {
  act(() => { root.render(<Harness {...props} />) })
}

function pacedText(): string {
  return container.querySelector('[data-testid="paced"]')?.textContent ?? ''
}

function flushFrames(count: number, frameMs = 16) {
  for (let index = 0; index < count; index += 1) {
    const callbacks = frameQueue
    frameQueue = []
    frameClock += frameMs
    act(() => { callbacks.forEach(callback => callback(frameClock)) })
  }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  frameQueue = []
  frameClock = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frameQueue.push(callback)
    return frameQueue.length
  })
  vi.stubGlobal('cancelAnimationFrame', () => { frameQueue = [] })
  window.matchMedia = vi.fn().mockReturnValue({ matches: false })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('nextRevealBoundary', () => {
  it('extends a mid-word index to the end of that word', () => {
    expect(nextRevealBoundary('hello brave world', 2)).toBe(5)
  })

  it('keeps an index that already sits on whitespace', () => {
    expect(nextRevealBoundary('hello brave world', 5)).toBe(5)
  })

  it('clamps to the text length', () => {
    expect(nextRevealBoundary('hello', 3)).toBe(5)
    expect(nextRevealBoundary('hello', 9)).toBe(5)
  })
})

describe('usePacedText', () => {
  it('renders non-progressive content immediately', () => {
    render({ messageId: 'static-1', content: LONG_TEXT, progressive: false })
    expect(pacedText()).toBe(LONG_TEXT)
    expect(frameQueue).toHaveLength(0)
  })

  it('reveals progressive content across frames at word boundaries', () => {
    render({ messageId: 'paced-1', content: LONG_TEXT })
    expect(pacedText()).toBe('')

    flushFrames(1)
    const partial = pacedText()
    expect(partial.length).toBeGreaterThan(0)
    expect(partial.length).toBeLessThan(LONG_TEXT.length)
    expect(LONG_TEXT.startsWith(partial)).toBe(true)
    expect(LONG_TEXT[partial.length]).toBe(' ')

    flushFrames(120)
    expect(pacedText()).toBe(LONG_TEXT)
  })

  it('holds the reveal until hold clears', () => {
    render({ messageId: 'held-1', content: LONG_TEXT, hold: true })
    expect(frameQueue).toHaveLength(0)
    flushFrames(5)
    expect(pacedText()).toBe('')

    render({ messageId: 'held-1', content: LONG_TEXT, hold: false })
    flushFrames(120)
    expect(pacedText()).toBe(LONG_TEXT)
  })

  it('shows the full text immediately under reduced motion', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true })
    render({ messageId: 'reduced-1', content: LONG_TEXT })
    expect(pacedText()).toBe(LONG_TEXT)
  })

  it('shows streamed text as it arrives under reduced motion, even if the stream never completes', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true })
    render({ messageId: 'reduced-stream-1', content: 'Basil can', streaming: true })
    expect(pacedText()).toBe('Basil can')
    expect(frameQueue).toHaveLength(0)
  })

  it('keeps pacing while streamed content grows', () => {
    render({ messageId: 'stream-1', content: 'Basil can', streaming: true })
    flushFrames(60)
    expect(pacedText()).toBe('Basil can')

    render({ messageId: 'stream-1', content: LONG_TEXT, streaming: true })
    expect(pacedText().startsWith('Basil can')).toBe(true)
    flushFrames(120)
    expect(pacedText()).toBe(LONG_TEXT)
  })

  it('does not replay a finished reveal after remount', () => {
    render({ messageId: 'replay-1', content: LONG_TEXT })
    flushFrames(120)
    expect(pacedText()).toBe(LONG_TEXT)

    act(() => { root.unmount() })
    root = createRoot(container)
    render({ messageId: 'replay-1', content: LONG_TEXT })
    expect(pacedText()).toBe(LONG_TEXT)
  })
})
