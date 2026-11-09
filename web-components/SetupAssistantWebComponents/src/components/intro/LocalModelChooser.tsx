import TokenizedSelect from '@shared/TokenizedSelect'

import type { SetupLocalModelChoice } from '@/types'

interface Props {
  choices: SetupLocalModelChoice[]
  /** The registry id of the local model the Local route currently names. */
  value: string | null
  onChange: (modelId: string) => void
  disabled?: boolean
}

function choiceLabel(choice: SetupLocalModelChoice): string {
  const size = choice.size_description ? ` (${choice.size_description})` : ''
  const state = choice.downloaded ? ' · on this Mac' : choice.can_copy_from_normal_basil ? ' · in your Basil' : ''
  return `${choice.display_name}${size}${state}`
}

/**
 * Validation builds only: lets a tester choose which local reasoning model setup uses, even when the hardware would default to a larger one.
 * The backend returns no choices outside a validation build, so this renders nothing there.
 */
export function LocalModelChooser({ choices, value, onChange, disabled = false }: Props) {
  if (choices.length < 2) return null
  const current = choices.some(choice => choice.model_id === value) ? value : choices[0].model_id
  return (
    <div className="local-model-chooser">
      <span className="local-model-chooser__label">Local model (validation only)</span>
      <TokenizedSelect
        value={current ?? ''}
        options={choices.map(choice => ({ value: choice.model_id, label: choiceLabel(choice) }))}
        onValueChange={onChange}
        disabled={disabled}
        ariaLabel="Local thinking model"
        className="local-model-chooser__select"
      />
    </div>
  )
}
