import type { ComfortLevel, ExpressItem, ExpressItemGroup, ExpressItemResult, ExpressApplyResult, ExpressPlan } from './expressTypes'

export const GROUP_ORDER: readonly ExpressItemGroup[] = ['downloads', 'learning', 'background', 'hotkeys']

export const GROUP_LABELS: Record<ExpressItemGroup, string> = {
  downloads: 'Models on this Mac',
  learning: 'Learning from your work',
  background: 'Listening and capture',
  hotkeys: 'Hotkeys',
}

const PERMISSION_LABELS: Record<string, string> = {
  screen_recording: 'screen recording access',
  microphone: 'microphone access',
}

const PERMISSION_ORDER = ['screen_recording', 'microphone'] as const

/** The plain summary shown first on the confirm screen for each comfort level. */
export function summaryForComfort(level: ComfortLevel, isYolo = false): string {
  if (level === 'cautious') {
    return 'Everything here stays on this Mac and needs no new macOS permission.'
  }
  if (level === 'balanced') {
    return 'This adds Activity Capture and Meeting and Call Detection to the Basil menu. They are switched on but do not start by themselves, and macOS asks for permission the first time you use them.'
  }
  if (isYolo) {
    return 'This turns on everything useful and downloads the models this Mac can run, except the Voice Listener, which starts unticked because it can react to sounds that are not you. Untick anything below that you do not want, or tick the Voice Listener if you want it. Anything under Listening and capture that stays ticked starts every time Basil launches.'
  }
  return 'This turns on everything you leave ticked below. Anything under Listening and capture starts every time Basil launches.'
}

export function comfortTitle(level: ComfortLevel): string {
  if (level === 'cautious') return 'Cautious'
  if (level === 'balanced') return 'Balanced'
  return 'All-in'
}

/** The items the person sees. A native item appears only when the app can act on it. */
export function visibleItems(plan: ExpressPlan, nativeHandledIds: ReadonlySet<string>): ExpressItem[] {
  return plan.items.filter(item => !item.native || nativeHandledIds.has(item.id))
}

/** The ids the review starts unticked: items the plan offers that it does not want on unless the person ticks them. */
export function defaultUntickedIds(plan: ExpressPlan): Set<string> {
  return new Set(plan.items.filter(item => item.selected && !item.default_ticked).map(item => item.id))
}

/** The ids that will be applied: every item the plan selected that the person has not unticked. */
export function selectedItemIds(items: readonly ExpressItem[], deselected: ReadonlySet<string>): string[] {
  return items.filter(item => item.selected && !deselected.has(item.id)).map(item => item.id)
}

export function groupItems(items: readonly ExpressItem[]): { group: ExpressItemGroup, items: ExpressItem[] }[] {
  return GROUP_ORDER
    .map(group => ({ group, items: items.filter(item => item.group === group) }))
    .filter(entry => entry.items.length > 0)
}

/** One sentence naming the macOS permissions the ticked items may trigger, or null when none are involved. */
export function permissionSentence(items: readonly ExpressItem[], selectedIds: readonly string[]): string | null {
  const wanted = new Set<string>()
  for (const item of items) {
    if (!selectedIds.includes(item.id)) continue
    for (const permission of item.permissions) wanted.add(permission)
  }
  const names = PERMISSION_ORDER.filter(permission => wanted.has(permission)).map(permission => PERMISSION_LABELS[permission])
  if (names.length === 0) return null
  return `macOS will ask for ${names.join(' and ')} the first time each is used.`
}

/** True when a preflight check failed, so the screen offers to check again. */
export function hasPreflightProblem(plan: ExpressPlan): boolean {
  return plan.preflight.some(check => !check.ok)
}

export function downloadSizeLabel(sizeGb: number | null): string | null {
  if (sizeGb === null || !Number.isFinite(sizeGb) || sizeGb <= 0) return null
  return sizeGb < 1 ? `${Math.round(sizeGb * 1024)} MB` : `${Number(sizeGb.toFixed(1))} GB`
}

export function failedResults(result: ExpressApplyResult): ExpressItemResult[] {
  return result.results.filter(item => item.outcome === 'failed')
}

export function itemStatusLabel(item: ExpressItem): string | null {
  if (item.already_done) return 'Already on'
  if (item.unavailable_reason) return 'Not available right now'
  return null
}
