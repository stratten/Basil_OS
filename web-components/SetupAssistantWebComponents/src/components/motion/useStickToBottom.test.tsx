// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, useRef } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { useStickToBottom } from './useStickToBottom'

interface Geometry {
  scrollHeight: number
  clientHeight: number
  scrollTop: number
}

let container: HTMLElement
let root: Root
let geometry: Geometry
let resizeCallbacks: ResizeObserverCallback[] = []

function Harness() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  useStickToBottom(scrollRef, contentRef)
  return (
    <div data-testid="scroller" ref={scrollRef}>
      <div ref={contentRef} />
    </div>
  )
}

function scroller(): HTMLElement {
  return container.querySelector('[data-testid="scroller"]') as HTMLElement
}

function installGeometry(element: HTMLElement) {
  Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => geometry.scrollHeight })
  Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => geometry.clientHeight })
  Object.defineProperty(element, 'scrollTop', {
    configurable: true,
    get: () => geometry.scrollTop,
    set: (value: number) => {
      geometry.scrollTop = Math.max(0, Math.min(value, geometry.scrollHeight - geometry.clientHeight))
    },
  })
}

function dispatchScroll() {
  scroller().dispatchEvent(new Event('scroll'))
}

function notifyResize() {
  resizeCallbacks.forEach(callback => callback([], {} as ResizeObserver))
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  resizeCallbacks = []
  geometry = { scrollHeight: 100, clientHeight: 158, scrollTop: 0 }
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resizeCallbacks.push(callback) }
    observe() {}
    disconnect() {}
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

function mount() {
  act(() => { root.render(<Harness />) })
  installGeometry(scroller())
}

describe('useStickToBottom', () => {
  it('stays pinned when a scroll event is read after later content growth was laid out', () => {
    mount()
    geometry.scrollHeight = 221
    notifyResize()
    expect(geometry.scrollTop).toBe(63)

    geometry.scrollHeight = 284
    dispatchScroll()
    notifyResize()

    expect(geometry.scrollTop).toBe(126)
  })

  it('releases the pin when the user scrolls up away from the bottom', () => {
    mount()
    geometry.scrollHeight = 600
    notifyResize()
    expect(geometry.scrollTop).toBe(442)
    dispatchScroll()

    geometry.scrollTop = 200
    dispatchScroll()
    geometry.scrollHeight = 700
    notifyResize()

    expect(geometry.scrollTop).toBe(200)
  })

  it('re-engages the pin when the user returns to the bottom', () => {
    mount()
    geometry.scrollHeight = 600
    notifyResize()
    dispatchScroll()
    geometry.scrollTop = 200
    dispatchScroll()

    geometry.scrollTop = 430
    dispatchScroll()
    geometry.scrollHeight = 700
    notifyResize()

    expect(geometry.scrollTop).toBe(542)
  })
})
