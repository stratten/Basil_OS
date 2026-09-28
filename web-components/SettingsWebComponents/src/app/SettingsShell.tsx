import { useEffect, useState } from 'react'
import { BasilWindowChrome } from '@shared/BasilWindowChrome'
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron'
import { closeSettingsShell, collapseSettingsShell, expandSettingsShell, minimizeSettingsShell } from '../services/shellBridge'
import { AccountSettingsApp } from './AccountSettingsApp'
import { AppearanceSettingsApp } from './AppearanceSettingsApp'
import { CaptureSettingsApp, CAPTURE_SUB_TABS, type CaptureSubTab } from './CaptureSettingsApp'
import { ConnectionsSettingsApp, CONNECTIONS_SUB_TABS, type ConnectionsSubTab } from './ConnectionsSettingsApp'
import { HomeSettingsApp, type HomeNavigationTarget } from './HomeSettingsApp'
import { HotkeySettingsApp } from './HotkeySettingsApp'
import { MeetingsSettingsApp } from './MeetingsSettingsApp'
import { MemoryIntelligenceSettingsApp } from './MemoryIntelligenceSettingsApp'
import { ModelsSettingsApp, MODELS_SUB_TABS, type ModelsSubTab } from './ModelsSettingsApp'
import { PermissionsSettingsApp, PERMISSIONS_SUB_TABS, type PermissionsSubTab } from './PermissionsSettingsApp'
import { ProfileSettingsApp } from './ProfileSettingsApp'
import { ReasoningAutomationApp, REASONING_AUTOMATION_SUB_TABS, type ReasoningAutomationSubTab } from './ReasoningAutomationApp'
import { TranscriptionSettingsApp, TRANSCRIPTION_SUB_TABS, type TranscriptionSubTab } from './TranscriptionSettingsApp'
import { WritingExamplesSettingsApp } from './WritingExamplesSettingsApp'
import { useHostThemeSync } from './useHostThemeSync'
import '../styles/hotkey-settings.css'

export type SettingsTabId =
  | 'home'
  | 'hotkeys'
  | 'profile'
  | 'memory-intelligence'
  | 'writing-examples'
  | 'models'
  | 'reasoning'
  | 'meetings'
  | 'capture'
  | 'transcription'
  | 'connections'
  | 'permissions'
  | 'account'
  | 'appearance'

interface SettingsSubTabSummary {
  id: string
  label: string
}

interface SettingsTabDefinition {
  id: SettingsTabId
  label: string
  migrated: boolean
  subTabs?: readonly SettingsSubTabSummary[]
}

interface SettingsNavigationGroup {
  id: string
  label: string
  tabs: readonly SettingsTabDefinition[]
}

interface NativeSettingsNavigationTarget {
  tabId: SettingsTabId
  subTabId?: string
}

declare global {
  interface Window {
    basilSettingsShell?: {
      navigate: (target: NativeSettingsNavigationTarget) => void
    }
  }
}

const NATIVE_NAVIGATION_EVENT = 'basil-settings-shell-navigate'
let pendingNativeNavigation: NativeSettingsNavigationTarget | null = null

function requestNativeNavigation(target: NativeSettingsNavigationTarget) {
  pendingNativeNavigation = target
  window.dispatchEvent(new CustomEvent<NativeSettingsNavigationTarget>(NATIVE_NAVIGATION_EVENT, { detail: target }))
}

window.basilSettingsShell = { navigate: requestNativeNavigation }

const SETTINGS_NAVIGATION: readonly SettingsNavigationGroup[] = [
  {
    id: 'home',
    label: 'General',
    tabs: [
      { id: 'home', label: 'Home', migrated: true },
      { id: 'hotkeys', label: 'Hotkeys', migrated: true },
    ],
  },
  {
    id: 'personalization',
    label: 'Personalization',
    tabs: [
      { id: 'profile', label: 'Profile', migrated: true },
      { id: 'memory-intelligence', label: 'Personal Context', migrated: true },
      { id: 'writing-examples', label: 'Writing Examples', migrated: true },
    ],
  },
  {
    id: 'capabilities',
    label: 'Capabilities',
    tabs: [
      { id: 'models', label: 'Models', migrated: true, subTabs: MODELS_SUB_TABS },
      { id: 'reasoning', label: 'Automation & Agents', migrated: true, subTabs: REASONING_AUTOMATION_SUB_TABS },
      { id: 'transcription', label: 'Transcription', migrated: true, subTabs: TRANSCRIPTION_SUB_TABS },
      { id: 'meetings', label: 'Meetings', migrated: true },
      { id: 'capture', label: 'Capture', migrated: true, subTabs: CAPTURE_SUB_TABS },
    ],
  },
  {
    id: 'system',
    label: 'System',
    tabs: [
      { id: 'connections', label: 'Connections', migrated: true, subTabs: CONNECTIONS_SUB_TABS },
      { id: 'permissions', label: 'Permissions', migrated: true, subTabs: PERMISSIONS_SUB_TABS },
      { id: 'account', label: 'Account', migrated: true },
      { id: 'appearance', label: 'Appearance & Format', migrated: true },
    ],
  },
]

export function SettingsShell() {
  useHostThemeSync()
  const [selectedTab, setSelectedTab] = useState<SettingsTabId>('home')
  const [expandedTabs, setExpandedTabs] = useState<ReadonlySet<SettingsTabId>>(new Set())
  const [subTabRequests, setSubTabRequests] = useState<Partial<Record<SettingsTabId, string>>>({})
  const activeTab = SETTINGS_NAVIGATION.flatMap((group) => group.tabs).find((tab) => tab.id === selectedTab)!

  function handleHomeNavigate(target: HomeNavigationTarget) {
    selectTab(target)
  }

  function selectTab(tabId: SettingsTabId) {
    setSelectedTab(tabId)
    const tab = SETTINGS_NAVIGATION.flatMap((group) => group.tabs).find((candidate) => candidate.id === tabId)
    setExpandedTabs(tab?.subTabs ? new Set([tabId]) : new Set())
  }

  function toggleExpanded(tabId: SettingsTabId) {
    setExpandedTabs((current) => {
      const next = new Set(current)
      if (next.has(tabId)) next.delete(tabId)
      else next.add(tabId)
      return next
    })
  }

  function selectSubTab(tabId: SettingsTabId, subTabId: string) {
    selectTab(tabId)
    setSubTabRequests((current) => ({ ...current, [tabId]: subTabId }))
  }

  useEffect(() => {
    function applyNativeNavigation(target: NativeSettingsNavigationTarget) {
      if (target.subTabId) selectSubTab(target.tabId, target.subTabId)
      else selectTab(target.tabId)
    }
    function handleNativeNavigation(event: Event) {
      const target = (event as CustomEvent<NativeSettingsNavigationTarget>).detail
      pendingNativeNavigation = null
      applyNativeNavigation(target)
    }

    window.addEventListener(NATIVE_NAVIGATION_EVENT, handleNativeNavigation)
    if (pendingNativeNavigation) {
      const target = pendingNativeNavigation
      pendingNativeNavigation = null
      applyNativeNavigation(target)
    }
    return () => window.removeEventListener(NATIVE_NAVIGATION_EVENT, handleNativeNavigation)
  }, [])

  return (
    <BasilWindowChrome
      title="Settings"
      onClose={closeSettingsShell}
      onMinimize={minimizeSettingsShell}
      onCollapse={collapseSettingsShell}
      onExpand={expandSettingsShell}
    >
      <div className="settings-shell">
        <nav className="settings-shell-navigation" aria-label="Settings">
          {SETTINGS_NAVIGATION.map((group) => (
            <section key={group.id} className="settings-shell-navigation-group" aria-labelledby={`settings-group-${group.id}`}>
              <h2 id={`settings-group-${group.id}`} className="settings-shell-navigation-heading">{group.label}</h2>
              {group.tabs.map((tab) => {
                const isExpanded = expandedTabs.has(tab.id)
                const selectedSubTabId = subTabRequests[tab.id] ?? (tab.id === 'models' ? 'reasoning' : undefined)
                return (
                  <div key={tab.id} className="settings-shell-nav-item-wrapper">
                    <div className="settings-shell-nav-item-row">
                      <button
                        id={`settings-nav-${tab.id}`}
                        type="button"
                        className={tab.id === selectedTab ? 'settings-shell-nav-item settings-shell-nav-item-selected' : 'settings-shell-nav-item'}
                        aria-current={tab.id === selectedTab ? 'page' : undefined}
                        disabled={!tab.migrated}
                        title={tab.migrated ? undefined : 'Coming soon'}
                        onClick={() => tab.migrated && selectTab(tab.id)}
                      >
                        {tab.label}
                      </button>
                      {tab.subTabs && (
                        <button
                          type="button"
                          className="settings-shell-nav-chevron"
                          aria-expanded={isExpanded}
                          aria-label={isExpanded ? `Collapse ${tab.label} sections` : `Expand ${tab.label} sections`}
                          onClick={() => toggleExpanded(tab.id)}
                        >
                          <ExecutionDisclosureChevron expanded={isExpanded} color="var(--text-tertiary)" />
                        </button>
                      )}
                    </div>
                    {tab.subTabs && isExpanded && (
                      <div className="settings-shell-nav-subitems">
                        {tab.subTabs.map((subTabItem) => (
                          <button
                            key={subTabItem.id}
                            type="button"
                            className={
                              selectedTab === tab.id && selectedSubTabId === subTabItem.id
                                ? 'settings-shell-nav-subitem settings-shell-nav-subitem-selected'
                                : 'settings-shell-nav-subitem'
                            }
                            onClick={() => selectSubTab(tab.id, subTabItem.id)}
                          >
                            {subTabItem.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          ))}
        </nav>

        <main className="settings-shell-content" aria-labelledby={`settings-nav-${selectedTab}`}>
          {selectedTab === 'home' && <HomeSettingsApp onNavigate={handleHomeNavigate} />}
          {selectedTab === 'hotkeys' && <HotkeySettingsApp />}
          {selectedTab === 'profile' && <ProfileSettingsApp />}
          {selectedTab === 'memory-intelligence' && <MemoryIntelligenceSettingsApp />}
          {selectedTab === 'writing-examples' && <WritingExamplesSettingsApp />}
          {selectedTab === 'models' && <ModelsSettingsApp requestedSubTab={subTabRequests.models as ModelsSubTab | undefined} />}
          {selectedTab === 'reasoning' && <ReasoningAutomationApp requestedSubTab={subTabRequests.reasoning as ReasoningAutomationSubTab | undefined} />}
          {selectedTab === 'capture' && <CaptureSettingsApp requestedSubTab={subTabRequests.capture as CaptureSubTab | undefined} />}
          {selectedTab === 'appearance' && <AppearanceSettingsApp />}
          {selectedTab === 'meetings' && <MeetingsSettingsApp />}
          {selectedTab === 'account' && <AccountSettingsApp />}
          {selectedTab === 'transcription' && <TranscriptionSettingsApp requestedSubTab={subTabRequests.transcription as TranscriptionSubTab | undefined} />}
          {selectedTab === 'permissions' && <PermissionsSettingsApp requestedSubTab={subTabRequests.permissions as PermissionsSubTab | undefined} />}
          {selectedTab === 'connections' && <ConnectionsSettingsApp requestedSubTab={subTabRequests.connections as ConnectionsSubTab | undefined} />}
          {selectedTab !== 'home' && selectedTab !== 'hotkeys' && selectedTab !== 'profile' && selectedTab !== 'memory-intelligence' && selectedTab !== 'writing-examples' && selectedTab !== 'models' && selectedTab !== 'reasoning' && selectedTab !== 'capture' && selectedTab !== 'appearance' && selectedTab !== 'meetings' && selectedTab !== 'account' && selectedTab !== 'transcription' && selectedTab !== 'permissions' && selectedTab !== 'connections' && (
            <div className="settings-shell-placeholder">{activeTab.label} settings have not been migrated to React yet.</div>
          )}
        </main>
      </div>
    </BasilWindowChrome>
  )
}
