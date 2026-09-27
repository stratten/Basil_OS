// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyProfileSettingsReady, onProfileEvent, requestClearProfile, saveProfile } from './profileBridge'
import type { ProfileFields } from '../types'

let postMessage: ReturnType<typeof vi.fn>

const FIELDS: ProfileFields = {
  fullName: 'Ada Lovelace',
  preferredName: null,
  email: null,
  jobTitle: null,
  companyName: null,
  industry: null,
  formality: null,
  tone: null,
  customInstructions: null,
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilProfileSettingsBridge: { postMessage } } }
})

describe('profileBridge', () => {
  it('sends a ready request', () => {
    notifyProfileSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a save request with a fresh request id', () => {
    const first = saveProfile(FIELDS)
    const second = saveProfile(FIELDS)
    expect(first).not.toBe(second)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'saveProfile', profile: FIELDS }))
  })

  it('sends a clear request with a fresh request id', () => {
    const id = requestClearProfile()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestClearProfile', requestId: id })
  })

  it('flushes queued native events in arrival order', () => {
    window.basilProfileSettings!.onEvent({ type: 'loadError', message: 'offline' })
    const received: string[] = []
    const unsubscribe = onProfileEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['offline'])
    unsubscribe()
  })
})
