import type { InteractionStyleGroup, InteractionStyleSelections } from '@/services/api'

interface IntroInteractionStyleProps {
  groups: InteractionStyleGroup[]
  selections: InteractionStyleSelections
  onSelectionsChange: (selections: InteractionStyleSelections) => void
}

// Returns the selections after the user toggles one statement: a single-choice group swaps its choice (or clears it when the same one is pressed again), and a multiple-choice group adds or removes the statement.
export function toggleInteractionStyleOption(
  selections: InteractionStyleSelections,
  group: InteractionStyleGroup,
  optionId: string,
): InteractionStyleSelections {
  const current = selections[group.id] ?? []
  const isSelected = current.includes(optionId)
  const next = group.multiple
    ? (isSelected ? current.filter(id => id !== optionId) : [...current, optionId])
    : (isSelected ? [] : [optionId])
  const { [group.id]: _removed, ...rest } = selections
  return next.length > 0 ? { ...rest, [group.id]: next } : rest
}

export function hasInteractionStyleSelection(selections: InteractionStyleSelections): boolean {
  return Object.values(selections).some(ids => ids.length > 0)
}

export function IntroInteractionStyle({ groups, selections, onSelectionsChange }: IntroInteractionStyleProps) {
  if (groups.length === 0) return null

  return (
    <div className="intro-style" role="group" aria-label="How I should work with you">
      {groups.map(group => (
        <div key={group.id} className="intro-style-group" role="group" aria-label={group.title}>
          <p className="intro-style-title">
            {group.title}
            <span className="intro-style-hint">{group.multiple ? 'Pick any' : 'Pick one'}</span>
          </p>
          <div className="intro-style-options">
            {group.options.map(option => {
              const isSelected = (selections[group.id] ?? []).includes(option.id)
              return (
                <button
                  key={option.id}
                  type="button"
                  className={`intro-style-option${isSelected ? ' selected' : ''}`}
                  aria-pressed={isSelected}
                  onClick={() => onSelectionsChange(toggleInteractionStyleOption(selections, group, option.id))}
                >
                  {option.label}
                </button>
              )
            })}
          </div>
        </div>
      ))}
      <p className="intro-style-footnote">Saved to your profile instructions when you continue. Change them any time.</p>
    </div>
  )
}
