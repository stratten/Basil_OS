// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApproveCircleIcon,
  ContinueCircleIcon,
  DenyCircleIcon,
  PauseCircleIcon,
  PlayCircleIcon,
  SkipCircleIcon,
  StopCircleIcon,
  WorkLogCircleIcon,
} from './CircleControlIcons'
import { PauseAction } from './PauseAction'
import { StopAction } from './StopAction'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function mount(node: React.ReactNode) {
  act(() => root.render(node))
}

function only(): HTMLButtonElement {
  const button = container.querySelector<HTMLButtonElement>('button')
  if (!button) throw new Error('Expected a button.')
  return button
}

describe('circle control icons', () => {
  it('draw as decorative circles that the host class sizes', () => {
    mount(<><StopCircleIcon /><PlayCircleIcon /><PauseCircleIcon /></>)
    const svgs = Array.from(container.querySelectorAll('svg'))
    expect(svgs).toHaveLength(3)
    svgs.forEach((svg) => {
      expect(svg.getAttribute('aria-hidden')).toBe('true')
      expect(svg.getAttribute('width')).toBeNull()
      expect(svg.querySelector('circle')).not.toBeNull()
    })
  })

  it('draws the decision circles the same way, and every one differs from the others', () => {
    mount(<><ApproveCircleIcon /><DenyCircleIcon /><StopCircleIcon /><ContinueCircleIcon /><SkipCircleIcon /><WorkLogCircleIcon /></>)
    const svgs = Array.from(container.querySelectorAll('svg'))
    expect(svgs).toHaveLength(6)
    svgs.forEach((svg) => {
      expect(svg.getAttribute('viewBox')).toBe('0 0 16 16')
      expect(svg.getAttribute('aria-hidden')).toBe('true')
      expect(svg.getAttribute('width')).toBeNull()
      expect(svg.querySelector('circle')).not.toBeNull()
    })
    const markup = svgs.map((svg) => svg.innerHTML)
    expect(new Set(markup).size).toBe(6)
  })
})

describe('StopAction', () => {
  it('keeps the word and the plain class by default', () => {
    mount(<StopAction isStopping={false} onStop={vi.fn()} />)
    expect(only().textContent).toBe('Stop')
    expect(only().className).toBe('basil-stop-action')
  })

  it('draws the stop icon in the icon variant and keeps the accessible name', () => {
    mount(<StopAction isStopping={false} onStop={vi.fn()} variant="icon" className="extra" />)
    expect(only().textContent).toBe('')
    expect(only().querySelector('svg')).not.toBeNull()
    expect(only().getAttribute('aria-label')).toBe('Stop')
    expect(only().className).toBe('basil-stop-action basil-stop-action--icon extra')
  })

  it('is disabled and named Stopping while stopping, and reports a click otherwise', () => {
    const onStop = vi.fn()
    mount(<StopAction isStopping onStop={onStop} variant="icon" />)
    expect(only().getAttribute('aria-label')).toBe('Stopping')
    expect(only().disabled).toBe(true)
    mount(<StopAction isStopping={false} onStop={onStop} variant="icon" />)
    act(() => only().click())
    expect(onStop).toHaveBeenCalledTimes(1)
  })
})

describe('PauseAction', () => {
  it('pauses from the running state', () => {
    const onPause = vi.fn()
    const onResume = vi.fn()
    mount(<PauseAction state="running" onPause={onPause} onResume={onResume} />)
    expect(only().getAttribute('aria-label')).toBe('Pause')
    act(() => only().click())
    expect(onPause).toHaveBeenCalledTimes(1)
    expect(onResume).not.toHaveBeenCalled()
  })

  it('resumes from the paused state and stays enabled', () => {
    const onPause = vi.fn()
    const onResume = vi.fn()
    mount(<PauseAction state="paused" isPending onPause={onPause} onResume={onResume} />)
    expect(only().getAttribute('aria-label')).toBe('Resume')
    expect(only().disabled).toBe(false)
    act(() => only().click())
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(onPause).not.toHaveBeenCalled()
  })

  it('waits while a pause is pending', () => {
    mount(<PauseAction state="running" isPending onPause={vi.fn()} onResume={vi.fn()} />)
    expect(only().disabled).toBe(true)
    expect(only().getAttribute('aria-label')).toBe('Pausing after this step')
  })
})
