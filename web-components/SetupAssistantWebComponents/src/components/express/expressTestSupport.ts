import type { ExpressItem, ExpressPlan } from './expressTypes'

export const THINKING_MODEL_ID = 'Qwen-qwen35-9b-q4km'

export function makeItem(overrides: Partial<ExpressItem> & Pick<ExpressItem, 'id' | 'group' | 'title'>): ExpressItem {
  return {
    summary: `${overrides.title} summary.`,
    caution: null,
    comfort: 'cautious',
    stays_on_this_mac: true,
    permissions: [],
    model_id: null,
    model_name: null,
    download_size_gb: null,
    native: false,
    already_done: false,
    unavailable_reason: null,
    selected: true,
    ...overrides,
  }
}

export function thinkingItem(overrides: Partial<ExpressItem> = {}): ExpressItem {
  return makeItem({
    id: 'download_thinking_model',
    group: 'downloads',
    title: 'Thinking model',
    model_id: THINKING_MODEL_ID,
    model_name: 'Qwen 3.5 9B',
    download_size_gb: 5.6,
    ...overrides,
  })
}

export function makePlan(overrides: Partial<ExpressPlan> = {}): ExpressPlan {
  return {
    comfort: 'all_in',
    device: {
      total_ram_gb: 16,
      memory_tier: 'standard',
      chip_label: 'Apple M2',
      is_apple_silicon: true,
      free_disk_gb: 100,
      summary: 'Apple M2, 16 GB of memory, 100 GB free',
    },
    preflight: [
      { id: 'disk', ok: true, message: 'There is room for the downloads.' },
      { id: 'network', ok: true, message: 'The download server is reachable.' },
    ],
    items: [
      thinkingItem(),
      makeItem({ id: 'learn_memory', group: 'learning', title: 'Memory after tasks' }),
      makeItem({ id: 'capture_activity', group: 'background', title: 'Activity Capture', permissions: ['screen_recording'] }),
      makeItem({ id: 'voice_listener', group: 'background', title: 'Voice Listener', comfort: 'all_in', permissions: ['microphone'], caution: 'In noisy places it can react to sounds that are not you.' }),
    ],
    notes: ['Everything here stays on this Mac while I think with the local model.'],
    thinking_model_available: true,
    ...overrides,
  }
}
