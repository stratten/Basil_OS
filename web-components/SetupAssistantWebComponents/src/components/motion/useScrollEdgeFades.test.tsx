// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, useRef } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { updateScrollEdgeAttributes, useScrollEdgeFades } from './useScrollEdgeFades'

interface Geometry {
  scrollHeight: number
  clientHeight: number
  scrollTop: number
}

let container: HTMLElement
let root: Root
let resizeCallbacks: ResizeObserverCallback[] = []

function installGeometry(element: HTMLElement, geometry: Geometry) {
  Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => geometry.scrollHeight })
  Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => geometry.clientHeight })
  Object.defineProperty(element, 'scrollTop', { configurable: true, get: () => geometry.scrollTop })
}

function edges(element: Element) {
  return {
    top: element.hasAttribute('data-overflow-top'),
    bottom: element.hasAttribute('data-overflow-bottom'),
  }
}

function Harness({ showMessages }: { showMessages: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null)
  useScrollEdgeFades(rootRef)
  return (
    <div ref={rootRef}>
      {showMessages && (
        <div className="basil-messages">
          <p>Row</p>
        </div>
      )}
      <div className="not-a-scroll-region" />
    </div>
  )
}

function messages(): HTMLElement {
  return container.querySelector('.basil-messages') as HTMLElement
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  resizeCallbacks = []
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resizeCallbacks.push(callback) }
    observe() {}
    unobserve() {}
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

describe('updateScrollEdgeAttributes', () => {
  it('reports which edges hide content', () => {
    const element = document.createElement('div')
    const geometry: Geometry = { scrollHeight: 100, clientHeight: 100, scrollTop: 0 }
    installGeometry(element, geometry)

    updateScrollEdgeAttributes(element)
    expect(edges(element)).toEqual({ top: false, bottom: false })

    geometry.scrollHeight = 400
    updateScrollEdgeAttributes(element)
    expect(edges(element)).toEqual({ top: false, bottom: true })

    geometry.scrollTop = 150
    updateScrollEdgeAttributes(element)
    expect(edges(element)).toEqual({ top: true, bottom: true })

    geometry.scrollTop = 300
    updateScrollEdgeAttributes(element)
    expect(edges(element)).toEqual({ top: true, bottom: false })
  })

  it('ignores sub-pixel remainders at either edge', () => {
    const element = document.createElement('div')
    installGeometry(element, { scrollHeight: 102, clientHeight: 100, scrollTop: 1 })

    updateScrollEdgeAttributes(element)
    expect(edges(element)).toEqual({ top: false, bottom: false })
  })
})

describe('useScrollEdgeFades', () => {
  it('updates a tracked region when it scrolls', () => {
    act(() => { root.render(<Harness showMessages />) })
    const geometry: Geometry = { scrollHeight: 400, clientHeight: 100, scrollTop: 0 }
    installGeometry(messages(), geometry)

    messages().dispatchEvent(new Event('scroll'))
    expect(edges(messages())).toEqual({ top: false, bottom: true })

    geometry.scrollTop = 300
    messages().dispatchEvent(new Event('scroll'))
    expect(edges(messages())).toEqual({ top: true, bottom: false })
  })

  it('re-checks tracked regions when their content resizes', () => {
    act(() => { root.render(<Harness showMessages />) })
    const geometry: Geometry = { scrollHeight: 100, clientHeight: 100, scrollTop: 0 }
    installGeometry(messages(), geometry)
    resizeCallbacks.forEach(callback => callback([], {} as ResizeObserver))
    expect(edges(messages())).toEqual({ top: false, bottom: false })

    geometry.scrollHeight = 260
    resizeCallbacks.forEach(callback => callback([], {} as ResizeObserver))
    expect(edges(messages())).toEqual({ top: false, bottom: true })
  })

  it('leaves elements outside the tracked selector alone', () => {
    act(() => { root.render(<Harness showMessages />) })
    const other = container.querySelector('.not-a-scroll-region') as HTMLElement
    installGeometry(other, { scrollHeight: 400, clientHeight: 100, scrollTop: 50 })

    other.dispatchEvent(new Event('scroll'))
    expect(edges(other)).toEqual({ top: false, bottom: false })
  })

  it('tracks scroll regions that mount later', async () => {
    act(() => { root.render(<Harness showMessages={false} />) })
    await act(async () => { root.render(<Harness showMessages />) })
    await act(async () => { await Promise.resolve() })
    installGeometry(messages(), { scrollHeight: 400, clientHeight: 100, scrollTop: 0 })

    messages().dispatchEvent(new Event('scroll'))
    expect(edges(messages())).toEqual({ top: false, bottom: true })
  })

  it('clears the attributes when the shell unmounts', () => {
    act(() => { root.render(<Harness showMessages />) })
    const element = messages()
    installGeometry(element, { scrollHeight: 400, clientHeight: 100, scrollTop: 0 })
    element.dispatchEvent(new Event('scroll'))
    expect(edges(element)).toEqual({ top: false, bottom: true })

    act(() => { root.render(<></>) })
    expect(edges(element)).toEqual({ top: false, bottom: false })
  })
})
