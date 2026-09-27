import { useEffect, useState } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { BrowserAutomationSettingsApp } from './BrowserAutomationSettingsApp'
import { ProactiveSuggestionsSettingsApp } from './ProactiveSuggestionsSettingsApp'
import { ReasoningDefaultsSettingsApp } from './ReasoningDefaultsSettingsApp'
import { SkillsSettingsApp } from './SkillsSettingsApp'

export type ReasoningAutomationSubTab = 'settings' | 'browser' | 'skills' | 'proactive'

export const REASONING_AUTOMATION_SUB_TABS: readonly SettingsSubTabDefinition<ReasoningAutomationSubTab>[] = [
  { id: 'settings', label: 'Settings' },
  { id: 'browser', label: 'Browser' },
  { id: 'skills', label: 'Skills' },
  { id: 'proactive', label: 'Proactive' },
]

function tabId(id: ReasoningAutomationSubTab): string {
  return `reasoning-automation-tab-${id}`
}

function panelId(id: ReasoningAutomationSubTab): string {
  return `reasoning-automation-panel-${id}`
}

export function ReasoningAutomationApp({ requestedSubTab }: { requestedSubTab?: ReasoningAutomationSubTab }) {
  const [selectedSubTab, setSelectedSubTab] = useState<ReasoningAutomationSubTab>(requestedSubTab ?? 'settings')

  useEffect(() => {
    if (requestedSubTab) setSelectedSubTab(requestedSubTab)
  }, [requestedSubTab])

  return (
    <div className="reasoning-automation-shell">
      <SettingsSubTabs
        tabs={REASONING_AUTOMATION_SUB_TABS}
        selected={selectedSubTab}
        onSelect={setSelectedSubTab}
        ariaLabel="Automation & Agents"
        getTabId={tabId}
        getPanelId={panelId}
      />
      <div
        id={panelId(selectedSubTab)}
        className="reasoning-automation-content"
        role="tabpanel"
        aria-labelledby={tabId(selectedSubTab)}
      >
        {selectedSubTab === 'settings' && <ReasoningDefaultsSettingsApp />}
        {selectedSubTab === 'browser' && <BrowserAutomationSettingsApp />}
        {selectedSubTab === 'skills' && <SkillsSettingsApp />}
        {selectedSubTab === 'proactive' && <ProactiveSuggestionsSettingsApp />}
      </div>
    </div>
  )
}
