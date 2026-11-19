import type { KeyboardEvent } from 'react'
import './settings-subtabs.css'

export interface SettingsSubTabDefinition<TId extends string> {
  id: TId
  label: string
}

interface SettingsSubTabsProps<TId extends string> {
  tabs: readonly SettingsSubTabDefinition<TId>[]
  selected: TId
  onSelect: (id: TId) => void
  ariaLabel: string
  getTabId: (id: TId) => string
  getPanelId: (id: TId) => string
}

export function SettingsSubTabs<TId extends string>({
  tabs,
  selected,
  onSelect,
  ariaLabel,
  getTabId,
  getPanelId,
}: SettingsSubTabsProps<TId>) {
  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, tab: TId) {
    const currentIndex = tabs.findIndex((candidate) => candidate.id === tab)
    const nextIndex =
      event.key === 'ArrowRight' ? (currentIndex + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (currentIndex - 1 + tabs.length) % tabs.length
          : event.key === 'Home' ? 0
            : event.key === 'End' ? tabs.length - 1
              : null
    if (nextIndex === null) return
    event.preventDefault()
    const nextTab = tabs[nextIndex]
    onSelect(nextTab.id)
    document.getElementById(getTabId(nextTab.id))?.focus()
  }

  return (
    <div className="settings-subtabs-picker" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={getTabId(tab.id)}
          aria-selected={tab.id === selected}
          aria-controls={getPanelId(tab.id)}
          tabIndex={tab.id === selected ? 0 : -1}
          className={tab.id === selected ? 'settings-subtabs-tab settings-subtabs-tab-selected' : 'settings-subtabs-tab'}
          onClick={() => onSelect(tab.id)}
          onKeyDown={(event) => handleKeyDown(event, tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
