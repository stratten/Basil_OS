// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SettingsShell } from './SettingsShell'
import { APPEARANCE_FIXTURE_SETTINGS } from '../fixtures/appearanceFixture'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function navigationButton(label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-shell-nav-item'))
    .find((button) => button.textContent === label)!
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = {
    messageHandlers: {
      basilAppearanceSettingsBridge: { postMessage },
      basilHotkeySettingsBridge: { postMessage },
      basilDateTimeSettingsBridge: { postMessage },
      basilProfileSettingsBridge: { postMessage },
      basilMemoryIntelligenceSettingsBridge: { postMessage },
      basilWritingExamplesSettingsBridge: { postMessage },
      basilModelsSettingsBridge: { postMessage },
      basilBrowserAutomationSettingsBridge: { postMessage },
      basilReasoningDefaultsSettingsBridge: { postMessage },
      basilSkillsSettingsBridge: { postMessage },
      basilMemoriesSettingsBridge: { postMessage },
      basilActivityCaptureSettingsBridge: { postMessage },
      basilMeetingDetectionSettingsBridge: { postMessage },
      basilAccountSettingsBridge: { postMessage },
      basilTranscriptionSettingsBridge: { postMessage },
      basilTranscriptionHistoryBridge: { postMessage },
      basilPermissionsApplicationBridge: { postMessage },
      basilPermissionsCommandSecurityBridge: { postMessage },
      basilConnectionsSettingsBridge: { postMessage },
      basilSettingsShellBridge: { postMessage },
      basilHomeSettingsBridge: { postMessage },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<SettingsShell />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SettingsShell', () => {
  it('renders the settled vertical navigation groups and all direct leaves', () => {
    expect(container.querySelector('.basil-window-title')?.textContent).toBe('Settings')
    expect(Array.from(container.querySelectorAll('.settings-shell-navigation-heading')).map((heading) => heading.textContent))
      .toEqual(['General', 'Personalization', 'Capabilities', 'System'])
    expect(container.querySelectorAll('.settings-shell-nav-item')).toHaveLength(14)
    expect(navigationButton('Appearance & Format')).not.toBeNull()
  })

  it('selects Home by default and renders its dashboard surface', () => {
    expect(navigationButton('Home').getAttribute('aria-current')).toBe('page')
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilHomeSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        fields: {
          setupAssistantPending: false,
          setupAssistantCompleted: true,
          setupAssistantStateAvailable: true,
          permissionsGrantedCount: 5,
          permissionsTotalCount: 5,
          enableMonitoringAtStartup: true,
          enableVoiceListenerAtStartup: false,
          startActivityCaptureAtLaunch: false,
          startMeetingDetectionAtLaunch: false,
          backgroundBehaviorAvailable: true,
          activityCaptureEnabled: true,
          activityCaptureAvailable: true,
          meetingDetectionEnabled: false,
          meetingDetectionAvailable: true,
          proactiveSuggestionsEnabled: false,
          proactiveSuggestionsAvailable: true,
          localModels: [],
          apiModels: [],
          customModels: [],
          selectedModelId: '',
          useApiModels: false,
          reasoningModelsAvailable: true,
          localTranscriptionModels: [],
          apiTranscriptionModels: [],
          selectedTranscriptionModelId: '',
          transcriptionModelsAvailable: true,
        },
      })
    })
    expect(container.querySelector('.home-settings-shell')).not.toBeNull()
  })

  it('selects Hotkeys when chosen and renders its existing React surface', () => {
    act(() => { navigationButton('Hotkeys').click() })
    expect(navigationButton('Hotkeys').getAttribute('aria-current')).toBe('page')
    expect(container.querySelector('.hotkey-settings-shell')).not.toBeNull()
  })

  it('enables the Connections leaf and hydrates its React surface', () => {
    const connections = navigationButton('Connections')
    expect(connections.disabled).toBe(false)
    expect(connections.title).toBeFalsy()
    act(() => { connections.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilConnectionsSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        starterServers: [],
        connections: [],
        callLogEntries: [],
        isLoading: false,
        isAddingConnection: false,
        isLoadingCallLog: false,
        errorMessage: null,
        statusMessage: null,
        pendingFlowFriendlyName: null,
        githubDeviceFlow: null,
        isPollingGitHubDeviceFlow: false,
        providerProfiles: [],
        isLoadingProviderProfiles: false,
        isMutatingProviderProfiles: false,
        providerProfilesStatusMessage: null,
        providerProfilesErrorMessage: null,
      })
    })
    expect(container.querySelector('.connections-settings-shell')).not.toBeNull()
  })

  it('wires the shared window chrome controls to the shell bridge', () => {
    act(() => { container.querySelector<HTMLButtonElement>('button[aria-label="Close window"]')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('button[aria-label="Minimize window"]')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'close' }))
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'minimize' }))
  })

  it('hydrates Appearance when its enabled leaf is selected', () => {
    act(() => { navigationButton('Appearance & Format').click() })
    act(() => {
      window.basilAppearanceSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        revision: 1,
        settings: APPEARANCE_FIXTURE_SETTINGS,
        availableFonts: ['Helvetica-Light', 'Arial'],
        theme: {
          backgroundPrimary: '#FFFFFF', backgroundSecondary: '#FFFFFF', backgroundTertiary: '#FFFFFF',
          primary: '#00308C', secondary: '#335599', textPrimary: '#000000', textSecondary: '#666666',
          textTertiary: '#999999', separatorColor: '#CCCCCC', fieldBorder: '#CCCCCC', recordingBase: '#8B0000',
          recordingAccent: '#FF6347', processingBase: '#7C3AED', processingAccent: '#DDD6FE', warningBase: '#FFA500',
        },
        fonts: { fontFamily: 'Helvetica-Light', fontFamilyMedium: 'Helvetica', fontFamilyBold: 'Helvetica-Bold' },
      })
    })
    expect(container.querySelector('#appearance-primary-color')).not.toBeNull()
  })

  it('reissues ready requests when switching between migrated leaves', () => {
    // 1 from the always-mounted host-theme sync on initial render, 1 from the
    // default Home leaf on initial render, 2 from selecting Appearance &
    // Format (the Appearance bridge plus the independently-mounted
    // DateTimeSection's own bridge), 1 from selecting Hotkeys again.
    act(() => { navigationButton('Appearance & Format').click() })
    act(() => { navigationButton('Hotkeys').click() })
    expect(postMessage.mock.calls.filter(([message]) => message.type === 'reactReady')).toHaveLength(5)
  })

  it('applies the host theme immediately on mount without requiring the Appearance leaf to be selected', () => {
    expect(navigationButton('Home').getAttribute('aria-current')).toBe('page')
    act(() => {
      window.basilAppearanceSettings!.onEvent({
        type: 'themeChanged',
        theme: {
          backgroundPrimary: '#111111', backgroundSecondary: '#222222', backgroundTertiary: '#333333',
          primary: '#444444', secondary: '#555555', textPrimary: '#666666', textSecondary: '#777777',
          textTertiary: '#888888', separatorColor: '#999999', fieldBorder: '#AAAAAA', recordingBase: '#BBBBBB',
          recordingAccent: '#CCCCCC', processingBase: '#DDDDDD', processingAccent: '#EEEEEE', warningBase: '#FF0000',
        },
        fonts: { fontFamily: 'CustomFont-Light', fontFamilyMedium: 'CustomFont-Medium', fontFamilyBold: 'CustomFont-Bold' },
      })
    })
    expect(document.documentElement.style.getPropertyValue('--primary')).toBe('#444444')
    expect(document.documentElement.style.getPropertyValue('--font-family-light')).toBe('CustomFont-Light')
    expect(document.documentElement.style.getPropertyValue('--font-family-medium')).toBe('CustomFont-Medium')
  })

  it('enables the Profile leaf and hydrates its React surface', () => {
    const profile = navigationButton('Profile')
    expect(profile.disabled).toBe(false)
    act(() => { profile.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilProfileSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        profile: {
          fullName: null, preferredName: null, email: null, jobTitle: null,
          companyName: null, industry: null, formality: null, tone: null, customInstructions: null,
        },
      })
    })
    expect(container.querySelector('.profile-settings-shell')).not.toBeNull()
  })

  it('enables the Personal Context leaf and hydrates its React surface', () => {
    const memoryIntelligence = navigationButton('Personal Context')
    expect(memoryIntelligence.disabled).toBe(false)
    act(() => { memoryIntelligence.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilMemoryIntelligenceSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: { memoryAfterTaskEnabled: false, memoryDailyEnabled: false, memoryDailyTimeLocal: '03:00', memoryProcessingModel: null },
        proposals: [],
        documents: [],
        availableModels: [],
      })
    })
    expect(container.querySelector('.memory-intelligence-shell')).not.toBeNull()
  })

  it('enables the Writing Examples leaf and hydrates its React surface', () => {
    const writingExamples = navigationButton('Writing Examples')
    expect(writingExamples.disabled).toBe(false)
    act(() => { writingExamples.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilWritingExamplesSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        activeFilter: 'all',
        samples: [],
        styleProfile: null,
        isLoadingSamples: false,
      })
    })
    expect(container.querySelector('.writing-examples-shell')).not.toBeNull()
  })

  it('enables the Models leaf and hydrates its React surface', () => {
    const models = navigationButton('Models')
    expect(models.disabled).toBe(false)
    act(() => { models.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilModelsSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoadingModels: false,
        localVisionFallbackEnabled: false,
        isLocalVisionFallbackModelInstalled: false,
        reasoningFallbackEnabled: false,
        reasoningFallbackModelId: '',
        reasoningGroups: [],
        transcriptionGroups: [],
      })
    })
    expect(container.querySelector('.models-settings-shell')).not.toBeNull()
  })

  it('exposes Models capability subtabs in the sidebar and routes them into the Models surface', () => {
    act(() => { navigationButton('Models').click() })
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="Collapse Models sections"]')).not.toBeNull()
    expect(Array.from(container.querySelectorAll('.settings-shell-nav-subitem')).map((item) => item.textContent))
      .toEqual(['Reasoning', 'Transcription'])

    const transcriptionSubItem = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-shell-nav-subitem'))
      .find((button) => button.textContent === 'Transcription')!
    act(() => { transcriptionSubItem.click() })
    act(() => {
      window.basilModelsSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoadingModels: false,
        localVisionFallbackEnabled: false,
        isLocalVisionFallbackModelInstalled: false,
        reasoningFallbackEnabled: false,
        reasoningFallbackModelId: '',
        reasoningGroups: [],
        transcriptionGroups: [],
      })
    })
    expect(transcriptionSubItem.classList.contains('settings-shell-nav-subitem-selected')).toBe(true)
    expect(Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === 'Transcription')?.getAttribute('aria-selected')).toBe('true')
  })

  it('enables the Automation & Agents leaf and hydrates its Settings sub-tab by default', () => {
    const reasoning = navigationButton('Automation & Agents')
    expect(reasoning.disabled).toBe(false)
    act(() => { reasoning.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilReasoningDefaultsSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: false,
        settings: {
          localModels: [],
          apiModels: [],
          customModels: [],
          selectedModelId: '',
          useApiModels: false,
          closeAssistantSessionOnInsert: false,
          assistantOutputPasteMode: 'never',
          useRegionSelection: false,
          agentTaskDefaultModality: 'voice',
          agentTaskAutoReopenOnCompletion: true,
          agentTaskPushToTalk: false,
          agentTaskPushToTalkThreshold: 750,
          assistantSessionDefaultModality: 'speak',
          assistantSessionPushToTalk: false,
          assistantSessionPushToTalkThreshold: 750,
        },
      })
    })
    expect(container.querySelector('.reasoning-defaults-shell')).not.toBeNull()
  })

  it('switches the Automation & Agents leaf to its Browser sub-tab from within the shell', () => {
    const reasoning = navigationButton('Automation & Agents')
    act(() => { reasoning.click() })
    const browserSubTab = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
      .find((button) => button.textContent === 'Browser')!
    act(() => { browserSubTab.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('expands only the selected grouped leaf and collapses it when leaving', () => {
    act(() => { navigationButton('Automation & Agents').click() })
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="Collapse Automation & Agents sections"]')).not.toBeNull()
    expect(Array.from(container.querySelectorAll('.settings-shell-nav-subitem')).map((item) => item.textContent))
      .toEqual(['Settings', 'Browser', 'Skills', 'Proactive'])

    act(() => { navigationButton('Capture').click() })
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="Collapse Capture sections"]')).not.toBeNull()
    expect(Array.from(container.querySelectorAll('.settings-shell-nav-subitem')).map((item) => item.textContent))
      .toEqual(['Activity Capture', 'Memories'])

    act(() => { navigationButton('Home').click() })
    expect(container.querySelector('.settings-shell-nav-subitems')).toBeNull()
  })

  it('keeps the sidebar sub-item highlight in sync with sub-tabs chosen at the top of the page', () => {
    const selectedSubItems = () =>
      Array.from(container.querySelectorAll('.settings-shell-nav-subitem-selected')).map((item) => item.textContent)

    act(() => { navigationButton('Automation & Agents').click() })
    expect(selectedSubItems()).toEqual(['Settings'])

    const proactiveSubItem = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-shell-nav-subitem'))
      .find((button) => button.textContent === 'Proactive')!
    act(() => { proactiveSubItem.click() })
    expect(selectedSubItems()).toEqual(['Proactive'])

    const skillsTopTab = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
      .find((button) => button.textContent === 'Skills')!
    act(() => { skillsTopTab.click() })
    expect(selectedSubItems()).toEqual(['Skills'])
    expect(skillsTopTab.getAttribute('aria-selected')).toBe('true')

    act(() => { navigationButton('Models').click() })
    expect(selectedSubItems()).toEqual(['Reasoning'])
    act(() => {
      window.basilModelsSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoadingModels: false,
        localVisionFallbackEnabled: false,
        isLocalVisionFallbackModelInstalled: false,
        reasoningGroups: [],
        transcriptionGroups: [],
      } as any)
    })
    const transcriptionFilter = Array.from(container.querySelectorAll<HTMLButtonElement>('.models-settings-filter-tab'))
      .find((button) => button.textContent === 'Transcription')!
    act(() => { transcriptionFilter.click() })
    expect(selectedSubItems()).toEqual(['Transcription'])
  })

  it('enables the Capture leaf directly, defaults to Activity Capture, and hydrates its React surface', () => {
    const capture = navigationButton('Capture')
    expect(capture.disabled).toBe(false)
    act(() => { capture.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: {
          enabled: true, frequencySeconds: 300, idleThresholdSeconds: 120, postWakeGraceSeconds: 5,
          excludedBundleIds: [], processingModel: '', processingMode: 'realtime',
          scheduledProcessingTime: '02:00', processingMaxRecords: 0, autoCleanupEnabled: false,
          retentionDays: 30, cleanupHour: 2, cleanupMinute: 0, maxStorageMb: 500,
        },
        status: {
          isSchedulerRunning: true, nextCaptureTime: null, todaysCaptures: 0,
          totalCapturesLast7Days: 0, totalCapturesLast30Days: 0, pendingCaptures: 0,
          failedCaptures: 0, skippedCaptureCount: 0, compactedCaptureCount: 0, lastPolicyDecision: null,
        },
        stats: null,
        processingProgress: null,
        availableModels: [],
        availableApps: [],
        excludedApps: [],
        retentionDayOptions: [0, 7, 14, 30, 60, 90, 180, 365],
        maxStorageOptions: [50, 100, 200, 500, 1000, 2000, 5000],
      })
    })
    expect(container.querySelector('.activity-capture-shell')).not.toBeNull()
  })

  it('expands the Capture sidebar chevron and jumps directly to the Memories sub-tab', () => {
    const chevron = container.querySelector<HTMLButtonElement>('button[aria-label="Expand Capture sections"]')!
    act(() => { chevron.click() })
    const memoriesSubItem = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-shell-nav-subitem'))
      .find((button) => button.textContent === 'Memories')!
    act(() => { memoriesSubItem.click() })
    expect(navigationButton('Capture').getAttribute('aria-current')).toBe('page')
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilMemoriesSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: {
          enabledSources: [],
          historyDays: 30,
          cardingEnabled: true,
          cardingIntervalMinutes: 15,
          limitPerSourcePerPass: 500,
          narrativeEnabled: true,
          narrativeModel: '',
          narrativeMode: 'scheduled',
          narrativeScheduledTime: '02:00',
          narrativeIntervalMinutes: 30,
          narrativeBatchSize: 50,
          narrativeMaxAttempts: 3,
          narrativeMaxRecords: 0,
        },
        stats: null,
        narrativeProgress: null,
        availableModels: [],
      })
    })
    expect(container.querySelector('.memories-shell')).not.toBeNull()
    expect(container.querySelector('.activity-capture-shell')).toBeNull()
  })

  it('collapses the Capture sidebar chevron sub-items again on a second click', () => {
    const chevron = container.querySelector<HTMLButtonElement>('button[aria-label="Expand Capture sections"]')!
    act(() => { chevron.click() })
    expect(container.querySelector('.settings-shell-nav-subitems')).not.toBeNull()
    act(() => { chevron.click() })
    expect(container.querySelector('.settings-shell-nav-subitems')).toBeNull()
  })

  it('enables the Meetings leaf directly and hydrates its React surface', () => {
    const meetings = navigationButton('Meetings')
    expect(meetings.disabled).toBe(false)
    act(() => { meetings.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilMeetingDetectionSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: {
          enabled: true,
          mode: 'prompt',
          pollSeconds: 20,
          excludedBundleIds: ['com.stratten.basil'],
          excludedAppNames: [],
          cooldownMinutes: 10,
          useCalendarEnrichment: false,
          requireCalendarMatch: false,
          autoEnd: true,
          inactivityTimeoutMinutes: 2,
        },
        availableApps: [],
        excludedApps: [],
        requiredBundleIds: ['com.stratten.basil'],
      })
    })
    expect(container.querySelector('.meetings-settings-shell')).not.toBeNull()
  })

  it('enables the Account leaf directly and hydrates its React surface', () => {
    const account = navigationButton('Account')
    expect(account.disabled).toBe(false)
    act(() => { account.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilAccountSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isAuthenticated: false,
        userEmail: '',
        subscriptionStatus: 'none',
        hasPaymentMethod: false,
        cardBrand: '',
        cardLast4: '',
        cardExpiration: '',
        apiKeyPreference: 'trial',
        basilCloudSelected: true,
        basilCloudBadge: 'Account required',
        basilCloudDescription: 'Sign in and add payment to use Basil Cloud.',
        isLoadingUsage: false,
        currentPeriodFormatted: '',
        totalCostFormatted: '$0.00',
        totalTokensFormatted: '0',
        usageByModel: [],
      })
    })
    expect(container.querySelector('.account-settings')).not.toBeNull()
  })

  it('enables the Transcription leaf and hydrates both its Settings and History bridges', () => {
    const transcription = navigationButton('Transcription')
    expect(transcription.disabled).toBe(false)
    act(() => { transcription.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilTranscriptionSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        settings: {
          selectedModel: 'whisper-1',
          apiModels: [{ id: 'whisper-1', displayName: 'Whisper', isApiModel: true, provider: 'openai' }],
          localModels: [],
          unloadDelaySeconds: 60,
          autoPasteTranscription: false,
          autoCloseOnPaste: false,
          startMeetingDetectionAtStartup: false,
          enablePushToTalk: false,
          pushToTalkThresholdMs: 750,
          textReplacements: [],
        },
        unloadDelayOptions: [{ seconds: 60, label: '1 minute' }],
      })
      window.basilTranscriptionHistory!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: false,
        error: null,
        timeFrameId: 'week',
        searchText: '',
        currentlyPlayingId: null,
        activeRetranscriptionId: null,
        retranscriptionProgressMessage: null,
        retranscriptionProgressFraction: null,
        currentGlobalTranscriptionModelId: 'whisper-1',
        availableRetranscriptionModels: [],
        transcriptions: [],
        timeFrameOptions: [{ id: 'week', label: '7 Days' }],
      })
    })
    expect(container.querySelector('.transcription-settings-panel')).not.toBeNull()
    expect(container.querySelector('.transcription-history-panel')).not.toBeNull()
  })

  it('opens the Transcription History sub-tab from a native navigation request', () => {
    act(() => {
      window.basilSettingsShell!.navigate({ tabId: 'transcription', subTabId: 'history' })
    })
    expect(navigationButton('Transcription').getAttribute('aria-current')).toBe('page')
    expect(container.querySelector<HTMLButtonElement>('#transcription-sub-tab-history')?.getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('#transcription-sub-panel-history')?.classList.contains('transcription-sub-tab-hidden')).toBe(false)
  })

  it('opens the Transcription Replacements sub-tab from a native navigation request', () => {
    act(() => {
      window.basilSettingsShell!.navigate({ tabId: 'transcription', subTabId: 'replacements' })
    })
    expect(navigationButton('Transcription').getAttribute('aria-current')).toBe('page')
    expect(container.querySelector<HTMLButtonElement>('#transcription-sub-tab-replacements')?.getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('#transcription-sub-panel-replacements')?.classList.contains('transcription-sub-tab-hidden')).toBe(false)
  })

  it('enables the Permissions leaf and hydrates both independent bridge domains', () => {
    const permissions = navigationButton('Permissions')
    expect(permissions.disabled).toBe(false)
    act(() => { permissions.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestPermissionStatus' }))
    act(() => {
      window.basilPermissionsApplication!.onEvent({
        type: 'init',
        protocolVersion: 1,
        permissions: {
          microphone: 'granted', accessibility: 'granted', inputMonitoring: 'unknown', screenRecording: 'granted', appleEvents: 'granted',
        },
      })
      window.basilPermissionsCommandSecurity!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: false,
        error: null,
        approvalSettings: null,
        whitelistPatterns: [],
      })
    })
    expect(container.querySelector('.permissions-settings-shell')).not.toBeNull()
    expect(container.textContent).toContain('Application Permissions')
  })
})
