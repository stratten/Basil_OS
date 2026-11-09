import { describeNativeBinding, describeResolution, hotkeyRowTitle, parseApplyOutcome, parseResolution } from '@/components/intro/hotkeyAlternatives'
import type { StagedHotkeyChoice } from '@/components/intro/useSetupHotkeys'
import { applySetupHotkey, isSetupNativeBridgeAvailable, resolveSetupHotkeys } from '@/services/bridge'

import type { ExpressItemResult } from './expressTypes'

export const HOTKEYS_ITEM_ID = 'hotkeys'

export const HOTKEYS_FAILED_MESSAGE = "I couldn't check your hotkeys. You can look at them in Settings, Hotkeys."

const NO_NATIVE_ITEMS: ReadonlySet<string> = new Set()
const HOTKEY_ITEMS: ReadonlySet<string> = new Set([HOTKEYS_ITEM_ID])

/** The express items the app can act on: the hotkey check, but only inside the Basil app window. The sets are constants so the prop never changes between renders. */
export function nativeHandledItemIds(): ReadonlySet<string> {
  return isSetupNativeBridgeAvailable() ? HOTKEY_ITEMS : NO_NATIVE_ITEMS
}

function failureMessage(error: unknown): string {
  // The bridge's own timeout sentence is not written for the person, so it is replaced.
  if (error instanceof Error && error.message && !error.message.startsWith("Setup action '")) return error.message
  return HOTKEYS_FAILED_MESSAGE
}

/** What the person decided on the confirm screen that the native items need when they run. */
export interface NativeExpressContext {
  /** The hotkeys the person chose or chose to keep. Every other clashing hotkey is switched to a free one. */
  hotkeyChoices: Readonly<Record<string, StagedHotkeyChoice>>
}

export const NO_NATIVE_CONTEXT: NativeExpressContext = { hotkeyChoices: {} }

/** Saves the hotkeys the person chose, one at a time, and says what happened to each. A save the Mac refuses is reported and leaves that hotkey as it was. */
async function applyChosenHotkeys(choices: Readonly<Record<string, StagedHotkeyChoice>>): Promise<{ sentences: string[], appliedCount: number }> {
  const sentences: string[] = []
  let appliedCount = 0
  for (const [id, choice] of Object.entries(choices)) {
    const title = hotkeyRowTitle(id, id)
    if (choice.kind === 'keep') {
      sentences.push(`I left ${title} as it is, as you chose.`)
      continue
    }
    try {
      const result = await applySetupHotkey(id, choice.binding, choice.acknowledged)
      const outcome = parseApplyOutcome(result.resultPayload)
      if (outcome?.saved) {
        sentences.push(`I set ${title} to ${describeNativeBinding(choice.binding) ?? 'the keys you chose'}, as you chose.`)
        appliedCount += 1
      } else {
        sentences.push(`I couldn't set ${title} to the keys you chose, so I left it as it is.`)
      }
    } catch {
      sentences.push(`I couldn't save the keys you chose for ${title}, so I left it as it is.`)
    }
  }
  return { sentences, appliedCount }
}

/** Runs the ticked native express items and returns one result for each. It never throws, and running it again changes nothing once the hotkeys are fixed. */
export async function applyNativeExpressItems(ids: readonly string[], context: NativeExpressContext = NO_NATIVE_CONTEXT): Promise<ExpressItemResult[]> {
  if (!ids.includes(HOTKEYS_ITEM_ID)) return []
  try {
    const chosen = await applyChosenHotkeys(context.hotkeyChoices)
    // The hotkeys the person decided on, chosen or kept, are never switched automatically.
    const result = await resolveSetupHotkeys(Object.keys(context.hotkeyChoices))
    const resolution = parseResolution(result.resultPayload)
    if (!resolution) {
      if (chosen.sentences.length === 0) return [{ id: HOTKEYS_ITEM_ID, outcome: 'failed', message: HOTKEYS_FAILED_MESSAGE }]
      return [{ id: HOTKEYS_ITEM_ID, outcome: chosen.appliedCount > 0 ? 'applied' : 'skipped', message: `${chosen.sentences.join(' ')} ${HOTKEYS_FAILED_MESSAGE}` }]
    }
    const automatic = resolution.changes.length > 0 || resolution.unresolved.length > 0 || chosen.sentences.length === 0
      ? describeResolution(resolution)
      : null
    const sentences = [...chosen.sentences]
    if (automatic) sentences.push(automatic.message)
    else sentences.push('You can change any hotkey in Settings, Hotkeys.')
    const changedAny = chosen.appliedCount > 0 || resolution.changes.length > 0
    // With nothing to change and nothing chosen, describeResolution says so, and that is a normal finish.
    const outcome = changedAny || (automatic !== null && chosen.sentences.length === 0 && automatic.outcome === 'applied') ? 'applied' : 'skipped'
    return [{ id: HOTKEYS_ITEM_ID, outcome, message: sentences.join(' ') }]
  } catch (error) {
    return [{ id: HOTKEYS_ITEM_ID, outcome: 'failed', message: failureMessage(error) }]
  }
}
