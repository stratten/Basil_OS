import { describe, expect, it } from 'vitest'

import {
  defaultUntickedIds,
  downloadSizeLabel,
  failedResults,
  groupItems,
  hasPreflightProblem,
  itemStatusLabel,
  permissionSentence,
  selectedItemIds,
  summaryForComfort,
  visibleItems,
} from './expressPlan'
import { makeItem, makePlan, thinkingItem } from './expressTestSupport'

describe('summaryForComfort', () => {
  it('says plainly what each level does', () => {
    expect(summaryForComfort('cautious')).toContain('stays on this Mac')
    expect(summaryForComfort('cautious')).toContain('no new macOS permission')
    expect(summaryForComfort('balanced')).toContain('do not start by themselves')
    expect(summaryForComfort('all_in')).toContain('everything you leave ticked')
    expect(summaryForComfort('all_in')).toContain('every time Basil launches')
    expect(summaryForComfort('all_in')).not.toContain('macOS will ask')
    expect(summaryForComfort('all_in', true)).toContain('downloads the models this Mac can run')
    expect(summaryForComfort('all_in', true)).toContain('every time Basil launches')
  })

  it('tells the person the Voice Listener starts unticked in the everything setup, so the summary stays true', () => {
    const text = summaryForComfort('all_in', true)
    expect(text).toContain('except the Voice Listener')
    expect(text).toContain('starts unticked')
    expect(text).toContain('tick the Voice Listener if you want it')
  })
})

describe('defaultUntickedIds', () => {
  it('lists only the offered items the plan wants unticked', () => {
    const plan = makePlan({
      items: [
        thinkingItem(),
        makeItem({ id: 'voice_listener', group: 'background', title: 'Voice Listener', default_ticked: false }),
        makeItem({ id: 'learn_skills', group: 'learning', title: 'Reusable workflows', already_done: true, selected: false, default_ticked: false }),
      ],
    })

    expect(Array.from(defaultUntickedIds(plan))).toEqual(['voice_listener'])
  })

  it('is empty when every item starts ticked', () => {
    expect(defaultUntickedIds(makePlan({ items: [thinkingItem()] })).size).toBe(0)
  })

  it('leaves the Voice Listener out of the ids that would be applied until it is ticked', () => {
    const plan = makePlan()
    const items = visibleItems(plan, new Set())

    expect(selectedItemIds(items, defaultUntickedIds(plan))).not.toContain('voice_listener')
    expect(selectedItemIds(items, new Set())).toContain('voice_listener')
  })
})

describe('visibleItems', () => {
  it('hides a native item until the app can act on it', () => {
    const plan = makePlan({
      items: [thinkingItem(), makeItem({ id: 'hotkeys', group: 'hotkeys', title: 'Hotkeys', native: true })],
    })

    expect(visibleItems(plan, new Set()).map(item => item.id)).toEqual(['download_thinking_model'])
    expect(visibleItems(plan, new Set(['hotkeys'])).map(item => item.id)).toEqual(['download_thinking_model', 'hotkeys'])
  })
})

describe('selectedItemIds', () => {
  it('keeps selected items, drops unticked ones, and never includes an unavailable or already-on item', () => {
    const items = [
      thinkingItem(),
      makeItem({ id: 'learn_memory', group: 'learning', title: 'Memory after tasks' }),
      makeItem({ id: 'learn_skills', group: 'learning', title: 'Reusable workflows', already_done: true, selected: false }),
      makeItem({ id: 'voice_listener', group: 'background', title: 'Voice Listener', unavailable_reason: 'No.', selected: false }),
    ]

    expect(selectedItemIds(items, new Set())).toEqual(['download_thinking_model', 'learn_memory'])
    expect(selectedItemIds(items, new Set(['learn_memory']))).toEqual(['download_thinking_model'])
  })

  it('returns nothing when everything is unticked', () => {
    expect(selectedItemIds([thinkingItem()], new Set(['download_thinking_model']))).toEqual([])
  })
})

describe('groupItems', () => {
  it('orders the groups the same way every time and skips empty ones', () => {
    const groups = groupItems([
      makeItem({ id: 'voice_listener', group: 'background', title: 'Voice Listener' }),
      thinkingItem(),
      makeItem({ id: 'learn_memory', group: 'learning', title: 'Memory after tasks' }),
    ])

    expect(groups.map(entry => entry.group)).toEqual(['downloads', 'learning', 'background'])
  })
})

describe('permissionSentence', () => {
  const items = [
    makeItem({ id: 'capture_activity', group: 'background', title: 'Activity Capture', permissions: ['screen_recording'] }),
    makeItem({ id: 'voice_listener', group: 'background', title: 'Voice Listener', permissions: ['microphone'] }),
    thinkingItem(),
  ]

  it('names both permissions in a fixed order when both are ticked', () => {
    expect(permissionSentence(items, ['voice_listener', 'capture_activity'])).toBe(
      'macOS will ask for screen recording access and microphone access the first time each is used.',
    )
  })

  it('names only what is ticked', () => {
    expect(permissionSentence(items, ['voice_listener'])).toBe('macOS will ask for microphone access the first time each is used.')
  })

  it('is null when nothing that needs a permission is ticked', () => {
    expect(permissionSentence(items, ['download_thinking_model'])).toBeNull()
    expect(permissionSentence(items, [])).toBeNull()
  })
})

describe('hasPreflightProblem', () => {
  it('is true only when a check failed', () => {
    expect(hasPreflightProblem(makePlan())).toBe(false)
    expect(hasPreflightProblem(makePlan({ preflight: [{ id: 'network', ok: false, message: 'No.' }] }))).toBe(true)
  })
})

describe('downloadSizeLabel', () => {
  it.each([
    [151 / 1024, '151 MB'],
    [670 / 1024, '670 MB'],
    [5.6, '5.6 GB'],
    [20, '20 GB'],
    [4.04, '4 GB'],
  ])('%s becomes %s', (size, label) => {
    expect(downloadSizeLabel(size)).toBe(label)
  })

  it.each([null, 0, -1, Number.NaN])('%s has no label', (size) => {
    expect(downloadSizeLabel(size)).toBeNull()
  })
})

describe('itemStatusLabel and failedResults', () => {
  it('labels already-on and unavailable items in words', () => {
    expect(itemStatusLabel(makeItem({ id: 'a', group: 'learning', title: 'A', already_done: true }))).toBe('Already on')
    expect(itemStatusLabel(makeItem({ id: 'a', group: 'learning', title: 'A', unavailable_reason: 'x' }))).toBe('Not available right now')
    expect(itemStatusLabel(makeItem({ id: 'a', group: 'learning', title: 'A' }))).toBeNull()
  })

  it('picks out only the failures', () => {
    const result = {
      comfort: 'cautious' as const,
      thinking_model_id: null,
      results: [
        { id: 'a', outcome: 'applied' as const, message: 'ok' },
        { id: 'b', outcome: 'failed' as const, message: 'no' },
      ],
    }

    expect(failedResults(result).map(item => item.id)).toEqual(['b'])
  })
})
