// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionPlaybackBar } from './TranscriptionPlaybackBar'

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

function renderBar(progress: { positionSeconds: number; durationSeconds: number } | null, onSeek = vi.fn()) {
  act(() => { root.render(<TranscriptionPlaybackBar progress={progress} onSeek={onSeek} />) })
  return onSeek
}

function track(): HTMLElement {
  const element = container.querySelector<HTMLElement>('[role="slider"]')!
  element.getBoundingClientRect = () => ({ left: 100, width: 200, top: 0, right: 300, bottom: 6, height: 6, x: 100, y: 0, toJSON: () => ({}) })
  return element
}

function pointer(element: HTMLElement, type: 'pointerdown' | 'pointermove' | 'pointerup', clientX: number) {
  act(() => { element.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX, button: 0 })) })
}

describe('TranscriptionPlaybackBar', () => {
  it('shows elapsed and total time and exposes slider semantics', () => {
    renderBar({ positionSeconds: 65.9, durationSeconds: 125 })
    const slider = track()
    expect(container.querySelector('.transcription-playback-elapsed')?.textContent).toBe('1:05')
    expect(container.querySelector('.transcription-playback-total')?.textContent).toBe('2:05')
    expect(slider.getAttribute('aria-valuemax')).toBe('125')
    expect(slider.getAttribute('aria-valuenow')).toBe('65')
    expect(slider.getAttribute('aria-valuetext')).toBe('1:05 of 2:05')
    expect((container.querySelector('.transcription-playback-fill') as HTMLElement).style.width).toBe(`${(65.9 / 125) * 100}%`)
  })

  it('shows hours for a long recording', () => {
    renderBar({ positionSeconds: 3600, durationSeconds: 10800 })
    expect(container.querySelector('.transcription-playback-total')?.textContent).toBe('3:00:00')
  })

  it('shows a loading state before the first progress event and when the duration is zero', () => {
    renderBar(null)
    expect(container.querySelector('[role="slider"]')).toBeNull()
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Loading audio')
    renderBar({ positionSeconds: 0, durationSeconds: 0 })
    expect(container.querySelector('[role="slider"]')).toBeNull()
  })

  it('seeks to the proportional position on pointer release, and not before', () => {
    const onSeek = renderBar({ positionSeconds: 0, durationSeconds: 100 })
    const slider = track()
    pointer(slider, 'pointerdown', 200)
    expect(onSeek).not.toHaveBeenCalled()
    expect(container.querySelector('.transcription-playback-elapsed')?.textContent).toBe('0:50')
    pointer(slider, 'pointermove', 250)
    pointer(slider, 'pointerup', 250)
    expect(onSeek).toHaveBeenCalledTimes(1)
    expect(onSeek).toHaveBeenCalledWith(75)
  })

  it('clamps a release outside the track to the ends', () => {
    const onSeek = renderBar({ positionSeconds: 10, durationSeconds: 100 })
    const slider = track()
    pointer(slider, 'pointerdown', 150)
    pointer(slider, 'pointerup', 9999)
    expect(onSeek).toHaveBeenLastCalledWith(100)
    pointer(slider, 'pointerdown', 150)
    pointer(slider, 'pointerup', -50)
    expect(onSeek).toHaveBeenLastCalledWith(0)
  })

  it('ignores a pointer release that had no matching press', () => {
    const onSeek = renderBar({ positionSeconds: 10, durationSeconds: 100 })
    pointer(track(), 'pointerup', 200)
    expect(onSeek).not.toHaveBeenCalled()
  })

  it('seeks with the keyboard in 5 second steps and to either end, clamped', () => {
    const onSeek = renderBar({ positionSeconds: 3, durationSeconds: 100 })
    const slider = track()
    const press = (key: string) => act(() => { slider.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })) })
    press('ArrowRight')
    expect(onSeek).toHaveBeenLastCalledWith(8)
    press('ArrowLeft')
    expect(onSeek).toHaveBeenLastCalledWith(0)
    press('End')
    expect(onSeek).toHaveBeenLastCalledWith(100)
    press('Home')
    expect(onSeek).toHaveBeenLastCalledWith(0)
    onSeek.mockClear()
    press('a')
    expect(onSeek).not.toHaveBeenCalled()
  })

  it('survives a non-finite position', () => {
    renderBar({ positionSeconds: Number.NaN, durationSeconds: 60 })
    expect(container.querySelector('.transcription-playback-elapsed')?.textContent).toBe('0:00')
  })
})
