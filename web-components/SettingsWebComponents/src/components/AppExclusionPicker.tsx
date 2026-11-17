import { useRef, useState } from 'react'
import IconChipList, { type IconChipEntry } from '@shared/IconChipList'
import type { MeetingDetectionAppOption } from '../types'

interface AppExclusionPickerProps {
  selectedBundleIds: string[]
  requiredBundleIds: readonly string[]
  availableApps: MeetingDetectionAppOption[]
  searchResults: MeetingDetectionAppOption[]
  knownAppsByBundleId: Record<string, MeetingDetectionAppOption>
  disabled?: boolean
  onFocusSearch: () => void
  onSearchQueryChange: (query: string) => void
  onAdd: (bundleId: string) => void
  onRemove: (bundleId: string) => void
}

export function AppExclusionPicker({
  selectedBundleIds,
  requiredBundleIds,
  availableApps,
  searchResults,
  knownAppsByBundleId,
  disabled,
  onFocusSearch,
  onSearchQueryChange,
  onAdd,
  onRemove,
}: AppExclusionPickerProps) {
  const [searchText, setSearchText] = useState('')
  const [isSearchFocused, setIsSearchFocused] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function handleSearchChange(value: string) {
    setSearchText(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onSearchQueryChange(value), 250)
  }

  const requiredSet = new Set(requiredBundleIds)
  const selectedSet = new Set(selectedBundleIds)
  const trimmedQuery = searchText.trim()
  const sourceApps = trimmedQuery.length === 0 ? availableApps : searchResults
  const filteredOptions = sourceApps.filter((app) => !selectedSet.has(app.bundleId))
  const showDropdown = isSearchFocused || trimmedQuery.length > 0
  const chipEntries: IconChipEntry[] = selectedBundleIds.map((bundleId) => {
    const app = resolve(bundleId)
    return {
      key: bundleId,
      name: app.name,
      iconSources: app.iconDataUrl ? [app.iconDataUrl] : [],
      lockedLabel: requiredSet.has(bundleId) ? 'Required' : undefined,
      kind: 'app',
    }
  })

  function resolve(bundleId: string): MeetingDetectionAppOption {
    return knownAppsByBundleId[bundleId] ?? { bundleId, name: bundleId, iconDataUrl: null }
  }

  return (
    <div className="app-exclusion-picker">
      <div className="app-exclusion-search">
        <input
          type="text"
          className="app-exclusion-search-input"
          placeholder="Search or choose an app..."
          value={searchText}
          disabled={disabled}
          onChange={(event) => handleSearchChange(event.target.value)}
          onFocus={() => { setIsSearchFocused(true); onFocusSearch() }}
          onBlur={() => setTimeout(() => setIsSearchFocused(false), 150)}
        />
      </div>
      {showDropdown && (
        <div className="app-exclusion-dropdown">
          {filteredOptions.length === 0 ? (
            <p className="app-exclusion-hint">No matching apps available.</p>
          ) : (
            filteredOptions.slice(0, 8).map((app) => (
              <button
                key={app.bundleId}
                type="button"
                className="app-exclusion-dropdown-item"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => { onAdd(app.bundleId); setSearchText(''); setIsSearchFocused(false) }}
              >
                {app.iconDataUrl && <img src={app.iconDataUrl} alt="" className="app-exclusion-icon" />}
                <span>{app.name}</span>
              </button>
            ))
          )}
        </div>
      )}
      <IconChipList
        groupLabel="Excluded apps"
        entries={chipEntries}
        removeDisabled={disabled}
        emptyText="No excluded apps selected."
        onRemove={(entry) => onRemove(entry.key)}
      />
    </div>
  )
}
