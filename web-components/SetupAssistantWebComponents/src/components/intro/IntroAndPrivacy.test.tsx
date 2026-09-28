// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroAndPrivacy } from './IntroAndPrivacy'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return {
    ok: true,
    text: vi.fn().mockResolvedValue(JSON.stringify(body)),
  }
}

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('IntroAndPrivacy', () => {
  it('shows saved capture preferences, current settings paths, and preserves them on continue', async () => {
    fetchMock
      .mockImplementation((path: string, init?: RequestInit) => {
        if (path === '/setup-assistant/model-access/options') {
          return Promise.resolve(jsonResponse({
            options: [{
              mode: 'local',
              available: true,
              requires_provider_key_input: false,
              local_model_id: 'phi2-2.7b',
            }],
          }))
        }
        if (path === '/settings/memory-intelligence' && init?.method === 'PUT') {
          return Promise.resolve(jsonResponse({ status: 'updated', updated_settings: {} }))
        }
        return Promise.resolve(jsonResponse({
          status: 'success',
          settings: {
            memory_after_task_enabled: true,
            skill_after_task_enabled: true,
          },
        }))
      })
    const onContinue = vi.fn()

    await act(async () => {
      root.render(
        <IntroAndPrivacy
          selectedModelAccess={{ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }}
          onSelectModelAccess={vi.fn()}
          onContinue={onContinue}
        />,
      )
      await Promise.resolve()
    })

    const continueButton = () => container.querySelector<HTMLButtonElement>('.intro-step-primary')!
    act(() => { continueButton().click() })

    expect(container.textContent).toContain('Personalization > Personal Context')
    expect(container.textContent).toContain('Capabilities > Automation & Agents > Skills')
    expect(container.querySelector<HTMLInputElement>('.intro-capture-toggle--memory input')?.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('.intro-capture-toggle--skill input')?.checked).toBe(true)

    act(() => { continueButton().click() })
    await act(async () => {
      continueButton().click()
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenCalledWith('/settings/memory-intelligence', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        memory_after_task_enabled: true,
        skill_after_task_enabled: true,
      }),
    })
    expect(onContinue).toHaveBeenCalledWith('')
  })

  it('does not overwrite capture preferences when their initial read fails', async () => {
    fetchMock.mockImplementation((path: string) => {
      if (path === '/setup-assistant/model-access/options') {
        return Promise.resolve(jsonResponse({
          options: [{
            mode: 'local',
            available: true,
            requires_provider_key_input: false,
            local_model_id: 'phi2-2.7b',
          }],
        }))
      }
      return Promise.reject(new Error('offline'))
    })
    const onContinue = vi.fn()

    await act(async () => {
      root.render(
        <IntroAndPrivacy
          selectedModelAccess={{ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }}
          onSelectModelAccess={vi.fn()}
          onContinue={onContinue}
        />,
      )
      await Promise.resolve()
    })

    const continueButton = () => container.querySelector<HTMLButtonElement>('.intro-step-primary')!
    act(() => { continueButton().click() })
    expect(container.textContent).toContain('continuing will leave them unchanged')

    act(() => { continueButton().click() })
    act(() => { continueButton().click() })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onContinue).toHaveBeenCalledWith('')
  })
})
