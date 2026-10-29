// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { initialState, reducer } from '@/state/setupAssistantStore/reducer'

import { type SetupAgentStreamApi, useSetupAgentStream } from './useSetupAgentStream'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root
let api: SetupAgentStreamApi | null = null

function Harness({ interactionStyle }: { interactionStyle: string[] }) {
  const store = {
    state: {
      ...initialState,
      interactionStyle,
      setupAgentModelAccess: { mode: 'local', resolved: true },
    },
  }
  api = useSetupAgentStream({ store: store as never })
  return null
}

beforeEach(() => {
  api = null
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('interaction style in the setup agent request', () => {
  it('starts empty and is set by the intro step', () => {
    expect(initialState.interactionStyle).toEqual([])
    const next = reducer(initialState, { type: 'set_interaction_style', interactionStyle: ['Keep replies short.'] })
    expect(next.interactionStyle).toEqual(['Keep replies short.'])
  })

  it('sends the chosen style with every turn so the conversation follows it from the first message', () => {
    act(() => { root.render(<Harness interactionStyle={['Keep replies short.', 'Use a table when comparing options.']} />) })

    const request = api!.buildRequest('hello', undefined, 'agent_synthesis', 'conversation')

    expect(request.current_step_context.interaction_style).toEqual([
      'Keep replies short.',
      'Use a table when comparing options.',
    ])
  })

  it('sends an empty style when the user chose nothing', () => {
    act(() => { root.render(<Harness interactionStyle={[]} />) })

    expect(api!.buildRequest('hello').current_step_context.interaction_style).toEqual([])
  })
})
