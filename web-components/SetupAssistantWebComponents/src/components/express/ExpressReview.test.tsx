// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { ExpressReview } from './ExpressReview'
import { makeItem, makePlan, thinkingItem } from './expressTestSupport'
import type { ExpressItem, ExpressPlan } from './expressTypes'

let container: HTMLElement
let root: Root

const onToggle = vi.fn()
const onCheckAgain = vi.fn()
const onApply = vi.fn()
const onChooseManual = vi.fn()
const onBackToStart = vi.fn()

interface RenderOptions {
  plan?: ExpressPlan
  items?: ExpressItem[]
  deselected?: string[]
  isYolo?: boolean
  isChecking?: boolean
  isApplying?: boolean
  applyError?: string | null
  withBack?: boolean
}

function renderReview(options: RenderOptions = {}) {
  const plan = options.plan ?? makePlan()
  act(() => {
    root.render(
      <ExpressReview
        plan={plan}
        items={options.items ?? plan.items}
        deselected={new Set(options.deselected ?? [])}
        isYolo={options.isYolo ?? false}
        isChecking={options.isChecking ?? false}
        isApplying={options.isApplying ?? false}
        applyError={options.applyError ?? null}
        onToggle={onToggle}
        onCheckAgain={onCheckAgain}
        onApply={onApply}
        onChooseManual={onChooseManual}
        onBackToStart={options.withBack ? onBackToStart : undefined}
      />,
    )
  })
}

function row(title: string): HTMLElement {
  const match = Array.from(container.querySelectorAll<HTMLElement>('.express-item')).find(element => element.textContent?.includes(title))
  if (!match) throw new Error(`No item containing "${title}"`)
  return match
}

function checkbox(title: string): HTMLInputElement {
  return row(title).querySelector<HTMLInputElement>('input[type="checkbox"]')!
}

function permissionNote(): string | undefined {
  return Array.from(container.querySelectorAll('.express-note'))
    .map(element => element.textContent ?? '')
    .find(text => text.startsWith('macOS will ask'))
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(element => element.textContent === label)
  if (!match) throw new Error(`No button "${label}"`)
  return match
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  for (const mock of [onToggle, onCheckAgain, onApply, onChooseManual, onBackToStart]) mock.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ExpressReview heading and summary', () => {
  it('names the comfort level for self-setup and says Everything for YOLO', () => {
    renderReview({ isYolo: false })
    expect(container.querySelector('.eyebrow')!.textContent).toBe('All-in setup')

    renderReview({ isYolo: true })
    expect(container.querySelector('.eyebrow')!.textContent).toBe('Everything')
  })

  it('shows the plain summary and the device line before the list', () => {
    renderReview()

    expect(container.querySelector('h2')!.textContent).toBe("Here is what I'll do on this Mac.")
    expect(container.querySelector('.express-review-summary')!.textContent).toContain('everything you leave ticked')
    expect(container.querySelector('.express-review-device')!.textContent).toBe('This Mac: Apple M2, 16 GB of memory, 100 GB free.')
    expect(container.querySelector('.express-note')!.textContent).toContain('stays on this Mac')
  })

  it('says YOLO downloads models and the all-in summary does not', () => {
    renderReview({ isYolo: true })
    expect(container.querySelector('.express-review-summary')!.textContent).toContain('downloads the models this Mac can run')

    renderReview({ isYolo: false })
    expect(container.querySelector('.express-review-summary')!.textContent).not.toContain('downloads')
  })
})

describe('ExpressReview item list', () => {
  it('is collapsed by default and counts what is ticked', () => {
    renderReview()

    const details = container.querySelector('details')!
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')!.textContent).toBe('What this turns on (4 of 4)')
  })

  it('updates the count when an item is unticked', () => {
    renderReview({ deselected: ['voice_listener'] })

    expect(container.querySelector('summary')!.textContent).toBe('What this turns on (3 of 4)')
    expect(checkbox('Voice Listener').checked).toBe(false)
    expect(checkbox('Activity Capture').checked).toBe(true)
  })

  it('groups the items in a fixed order with plain headings', () => {
    renderReview()

    expect(Array.from(container.querySelectorAll('.express-group h3')).map(heading => heading.textContent)).toEqual([
      'Models on this Mac',
      'Learning from your work',
      'Listening and capture',
    ])
  })

  it('shows the model, its size and why it was chosen on the thinking model', () => {
    renderReview()

    const text = row('Thinking model').textContent!
    expect(text).toContain('5.6 GB')
    expect(text).toContain('Chosen for this Mac')
    expect(text).toContain('Model: Qwen 3.5 9B')
  })

  it('shows an item caution in words', () => {
    renderReview()

    expect(row('Voice Listener').textContent).toContain('In noisy places it can react to sounds that are not you.')
  })

  it('reports a toggle for the item that was clicked, and only that one', () => {
    renderReview()

    act(() => { checkbox('Memory after tasks').click() })

    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(onToggle).toHaveBeenCalledWith('learn_memory')
  })

  it('shows an item that is already on as ticked, locked and labeled, with no download size', () => {
    renderReview({
      items: [thinkingItem({ already_done: true, selected: false })],
      plan: makePlan({ items: [thinkingItem({ already_done: true, selected: false })] }),
    })

    const input = checkbox('Thinking model')
    expect(input.checked).toBe(true)
    expect(input.disabled).toBe(true)
    expect(row('Thinking model').textContent).toContain('Already on')
    expect(row('Thinking model').textContent).not.toContain('5.6 GB')
  })

  it('shows an unavailable item as unticked, locked, with the reason in words', () => {
    const unavailable = makeItem({
      id: 'download_voice_quality',
      group: 'downloads',
      title: 'High-quality voice model',
      selected: false,
      unavailable_reason: 'There is not enough free disk space for it.',
    })
    renderReview({ items: [unavailable], plan: makePlan({ items: [unavailable] }) })

    const input = checkbox('High-quality voice model')
    expect(input.checked).toBe(false)
    expect(input.disabled).toBe(true)
    expect(row('High-quality voice model').textContent).toContain('Not available right now. There is not enough free disk space for it.')
  })

  it('lets an empty selection through, because Do it with nothing ticked is valid', () => {
    renderReview({ deselected: ['download_thinking_model', 'learn_memory', 'capture_activity', 'voice_listener'] })

    expect(container.querySelector('summary')!.textContent).toBe('What this turns on (0 of 4)')
    expect(button('Do it').disabled).toBe(false)
  })
})

describe('ExpressReview permissions sentence', () => {
  it('names both permissions when both items are ticked', () => {
    renderReview()

    expect(permissionNote()).toBe('macOS will ask for screen recording access and microphone access the first time each is used.')
  })

  it('drops a permission when its item is unticked', () => {
    renderReview({ deselected: ['voice_listener'] })

    expect(permissionNote()).toBe('macOS will ask for screen recording access the first time each is used.')
  })

  it('shows no permission sentence when nothing that needs one is ticked', () => {
    renderReview({ deselected: ['capture_activity', 'voice_listener'] })

    expect(permissionNote()).toBeUndefined()
  })
})

describe('ExpressReview checks', () => {
  it('lists passing checks in words and offers no recheck', () => {
    renderReview()

    const checks = Array.from(container.querySelectorAll('.express-check'))
    expect(checks.map(check => check.querySelector('.express-check-state')!.textContent)).toEqual(['OK', 'OK'])
    expect(container.querySelector('.express-check-again')).toBeNull()
  })

  it('shows a failing check as Needs attention and offers Check again', () => {
    renderReview({ plan: makePlan({ preflight: [
      { id: 'disk', ok: true, message: 'There is room for the downloads.' },
      { id: 'network', ok: false, message: "I can't reach the download server." },
    ] }) })

    const states = Array.from(container.querySelectorAll('.express-check-state')).map(element => element.textContent)
    expect(states).toEqual(['OK', 'Needs attention'])

    act(() => { button('Check again').click() })
    expect(onCheckAgain).toHaveBeenCalledTimes(1)
  })

  it('disables Check again while it is checking', () => {
    renderReview({
      isChecking: true,
      plan: makePlan({ preflight: [{ id: 'network', ok: false, message: 'No.' }] }),
    })

    expect(button('Checking…').disabled).toBe(true)
  })
})

describe('ExpressReview actions', () => {
  it('applies when Do it is pressed and offers the step-by-step path', () => {
    renderReview()

    act(() => { button('Do it').click() })
    act(() => { button('Set it up step by step instead').click() })

    expect(onApply).toHaveBeenCalledTimes(1)
    expect(onChooseManual).toHaveBeenCalledTimes(1)
  })

  it('offers Back to the first screen only when a way back is given, and locks it while applying', () => {
    renderReview()
    expect(Array.from(container.querySelectorAll('button')).some(element => element.textContent === '← Back')).toBe(false)

    renderReview({ withBack: true })
    act(() => { button('← Back').click() })
    expect(onBackToStart).toHaveBeenCalledTimes(1)

    renderReview({ withBack: true, isApplying: true })
    expect(button('← Back').disabled).toBe(true)
  })

  it('locks both buttons while applying', () => {
    renderReview({ isApplying: true })

    expect(button('Working…').disabled).toBe(true)
    expect(button('Set it up step by step instead').disabled).toBe(true)
  })

  it('shows an apply failure as an alert and keeps Do it available', () => {
    renderReview({ applyError: 'Downloads are not ready yet. Try again in a moment.' })

    expect(container.querySelector('[role="alert"]')!.textContent).toBe('Downloads are not ready yet. Try again in a moment.')
    expect(button('Do it').disabled).toBe(false)
  })

  it('shows notes from the plan', () => {
    renderReview({ plan: makePlan({ notes: ['This Mac has limited memory, so I chose a smaller thinking model.'] }) })

    expect(container.textContent).toContain('This Mac has limited memory, so I chose a smaller thinking model.')
  })
})
