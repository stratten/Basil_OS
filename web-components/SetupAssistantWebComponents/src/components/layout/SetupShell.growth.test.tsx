// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SetupShell } from './SetupShell'
import type { SetupStage } from '@/state/setupAssistantStore'

const postMessage = vi.fn()

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('SetupShell window growth', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    postMessage.mockReset()
    window.webkit = { messageHandlers: { setupAssistant: { postMessage } } }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  function render(stage: SetupStage) {
    act(() => {
      root.render(
        <SetupShell setupStage={stage} hasActiveArtifact={false} onSkip={() => {}}>
          <div />
        </SetupShell>,
      )
    })
  }

  const growCalls = () =>
    postMessage.mock.calls.filter(([message]) => message?.name === 'growSetupAssistantForConversation')

  it('asks the native window to grow once when the conversation step begins', () => {
    render('orientation')
    expect(growCalls()).toHaveLength(0)

    render('conversation')
    expect(growCalls()).toHaveLength(1)

    render('conversation')
    expect(growCalls()).toHaveLength(1)
  })

  it('does not ask to grow on any other step', () => {
    for (const stage of ['welcome', 'intro_and_privacy', 'orientation', 'wrap_up'] as SetupStage[]) {
      render(stage)
    }
    expect(growCalls()).toHaveLength(0)
  })
})
