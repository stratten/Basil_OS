import { useEffect, useState } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { ActivityCaptureSettingsApp } from './ActivityCaptureSettingsApp'
import { MemoriesSettingsApp } from './MemoriesSettingsApp'
import '../styles/capture-settings.css'

export type CaptureSubTab = 'activity-capture' | 'memories'

export const CAPTURE_SUB_TABS: readonly SettingsSubTabDefinition<CaptureSubTab>[] = [
  { id: 'activity-capture', label: 'Activity Capture' },
  { id: 'memories', label: 'Memories' },
]

function tabId(id: CaptureSubTab): string {
  return `capture-tab-${id}`
}

function panelId(id: CaptureSubTab): string {
  return `capture-panel-${id}`
}

export function CaptureSettingsApp({
  requestedSubTab,
  onSubTabChange,
}: {
  requestedSubTab?: CaptureSubTab
  onSubTabChange?: (subTab: CaptureSubTab) => void
}) {
  const [selectedSubTab, setSelectedSubTab] = useState<CaptureSubTab>(requestedSubTab ?? 'activity-capture')

  useEffect(() => {
    if (requestedSubTab) setSelectedSubTab(requestedSubTab)
  }, [requestedSubTab])

  function selectSubTab(subTab: CaptureSubTab) {
    setSelectedSubTab(subTab)
    onSubTabChange?.(subTab)
  }

  return (
    <div className="capture-settings-shell">
      <SettingsSubTabs
        tabs={CAPTURE_SUB_TABS}
        selected={selectedSubTab}
        onSelect={selectSubTab}
        ariaLabel="Capture"
        getTabId={tabId}
        getPanelId={panelId}
      />
      <div
        id={panelId(selectedSubTab)}
        className="capture-settings-content"
        role="tabpanel"
        aria-labelledby={tabId(selectedSubTab)}
      >
        {selectedSubTab === 'activity-capture' && <ActivityCaptureSettingsApp />}
        {selectedSubTab === 'memories' && <MemoriesSettingsApp />}
      </div>
    </div>
  )
}
