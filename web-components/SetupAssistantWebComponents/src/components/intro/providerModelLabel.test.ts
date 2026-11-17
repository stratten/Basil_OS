import { describe, expect, it } from 'vitest'

import { providerModelLabel } from './providerModelLabel'

const choice = { provider: 'anthropic', model_id: 'claude-sonnet', display_name: 'Claude Sonnet', recommended: false }

describe('providerModelLabel', () => {
  it('shows the plain name for a model that is neither recommended nor switched on', () => {
    expect(providerModelLabel(choice)).toBe('Claude Sonnet')
  })

  it('marks the recommended model', () => {
    expect(providerModelLabel({ ...choice, recommended: true })).toBe('Claude Sonnet (Recommended)')
  })

  it('marks a model the person switched on in Settings', () => {
    expect(providerModelLabel({ ...choice, enabled: true })).toBe('Claude Sonnet (On in Settings)')
  })

  it('marks both together, and treats a missing flag from an older response as not switched on', () => {
    expect(providerModelLabel({ ...choice, recommended: true, enabled: true })).toBe('Claude Sonnet (Recommended, On in Settings)')
    expect(providerModelLabel({ ...choice, enabled: undefined })).toBe('Claude Sonnet')
  })
})
