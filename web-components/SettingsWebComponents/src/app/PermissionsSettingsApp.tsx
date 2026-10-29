import { useEffect, useState } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { PermissionsApplicationPanel } from '../components/PermissionsApplicationPanel'
import { PermissionsCommandSecurityPanel } from '../components/PermissionsCommandSecurityPanel'
import '../styles/permissions-settings.css'

export type PermissionsSubTab = 'application' | 'command-security'

export const PERMISSIONS_SUB_TABS: readonly SettingsSubTabDefinition<PermissionsSubTab>[] = [
  { id: 'application', label: 'Application' },
  { id: 'command-security', label: 'Command Security' },
]

function tabId(id: PermissionsSubTab): string {
  return `permissions-sub-tab-${id}`
}

function panelId(id: PermissionsSubTab): string {
  return `permissions-sub-panel-${id}`
}

export function PermissionsSettingsApp({
  requestedSubTab,
  onSubTabChange,
}: {
  requestedSubTab?: PermissionsSubTab
  onSubTabChange?: (subTab: PermissionsSubTab) => void
}) {
  const [subTab, setSubTab] = useState<PermissionsSubTab>(requestedSubTab ?? 'application')

  useEffect(() => {
    if (requestedSubTab) setSubTab(requestedSubTab)
  }, [requestedSubTab])

  function selectSubTab(next: PermissionsSubTab) {
    setSubTab(next)
    onSubTabChange?.(next)
  }

  return (
    <div className="permissions-settings-shell">
      <SettingsSubTabs
        tabs={PERMISSIONS_SUB_TABS}
        selected={subTab}
        onSelect={selectSubTab}
        ariaLabel="Permissions sections"
        getTabId={tabId}
        getPanelId={panelId}
      />

      <div id={panelId('application')} role="tabpanel" aria-labelledby={tabId('application')} className={subTab === 'application' ? '' : 'permissions-sub-tab-hidden'}>
        <PermissionsApplicationPanel />
      </div>
      <div id={panelId('command-security')} role="tabpanel" aria-labelledby={tabId('command-security')} className={subTab === 'command-security' ? '' : 'permissions-sub-tab-hidden'}>
        <PermissionsCommandSecurityPanel />
      </div>
    </div>
  )
}
