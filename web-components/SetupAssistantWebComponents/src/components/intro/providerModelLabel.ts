import type { SetupAgentProviderModelChoice } from '@/types'

/** The text for one model in the setup model picker. It marks the recommended model and the models the person already switched on in Settings, so the list can show every visible model without hiding the ones they chose. */
export function providerModelLabel(choice: SetupAgentProviderModelChoice): string {
  const marks = [
    choice.recommended ? 'Recommended' : null,
    choice.enabled ? 'On in Settings' : null,
  ].filter((mark): mark is string => mark !== null)
  return marks.length > 0 ? `${choice.display_name} (${marks.join(', ')})` : choice.display_name
}
