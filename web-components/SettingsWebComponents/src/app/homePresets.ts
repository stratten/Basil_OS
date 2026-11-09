import type { HomeQuickToggleField, HomeSettingsFields } from '../types'

export type HomePresetId = 'everything' | 'conservative'

export interface HomePresetStep {
  field: HomeQuickToggleField
  value: boolean
}

export interface HomePresetPlan {
  steps: HomePresetStep[]
  // Labels of settings the preset wants to change but cannot, because their status is unavailable right now.
  unavailable: string[]
}

const FIELD_LABELS: Record<HomeQuickToggleField, string> = {
  enableMonitoringAtStartup: 'Hotkeys at startup',
  enableVoiceListenerAtStartup: 'Voice Listener at startup',
  activityCaptureEnabled: 'Activity Capture',
  startActivityCaptureAtLaunch: 'Start Activity Capture on launch',
  meetingDetectionEnabled: 'Meeting/Call Detection',
  startMeetingDetectionAtLaunch: 'Start Meeting/Call Detection on launch',
  proactiveSuggestionsEnabled: 'Proactive Suggestions',
}

const AVAILABILITY: Record<HomeQuickToggleField, keyof HomeSettingsFields> = {
  enableMonitoringAtStartup: 'backgroundBehaviorAvailable',
  enableVoiceListenerAtStartup: 'backgroundBehaviorAvailable',
  activityCaptureEnabled: 'activityCaptureAvailable',
  startActivityCaptureAtLaunch: 'activityCaptureAvailable',
  meetingDetectionEnabled: 'meetingDetectionAvailable',
  startMeetingDetectionAtLaunch: 'meetingDetectionAvailable',
  proactiveSuggestionsEnabled: 'proactiveSuggestionsAvailable',
}

// The order matters: a feature is switched on before its launch preference, and its launch preference is switched off before the feature is.
const EVERYTHING_ON: HomePresetStep[] = [
  { field: 'enableMonitoringAtStartup', value: true },
  { field: 'enableVoiceListenerAtStartup', value: true },
  { field: 'activityCaptureEnabled', value: true },
  { field: 'startActivityCaptureAtLaunch', value: true },
  { field: 'meetingDetectionEnabled', value: true },
  { field: 'startMeetingDetectionAtLaunch', value: true },
  { field: 'proactiveSuggestionsEnabled', value: true },
]

// Hotkeys stay on because they are how Basil is invoked. Everything that listens, captures or interrupts is off.
const CONSERVATIVE: HomePresetStep[] = [
  { field: 'enableMonitoringAtStartup', value: true },
  { field: 'enableVoiceListenerAtStartup', value: false },
  { field: 'startActivityCaptureAtLaunch', value: false },
  { field: 'activityCaptureEnabled', value: false },
  { field: 'startMeetingDetectionAtLaunch', value: false },
  { field: 'meetingDetectionEnabled', value: false },
  { field: 'proactiveSuggestionsEnabled', value: false },
]

export const HOME_PRESET_LABELS: Record<HomePresetId, string> = {
  everything: 'Enable everything',
  conservative: 'Conservative',
}

/** The steps a preset needs from the current settings: only fields that differ and whose status is available. */
export function planHomePreset(preset: HomePresetId, fields: HomeSettingsFields): HomePresetPlan {
  const steps: HomePresetStep[] = []
  const unavailable: string[] = []
  for (const step of preset === 'everything' ? EVERYTHING_ON : CONSERVATIVE) {
    if (fields[step.field] === step.value) continue
    if (!fields[AVAILABILITY[step.field]]) {
      unavailable.push(FIELD_LABELS[step.field])
      continue
    }
    steps.push(step)
  }
  return { steps, unavailable }
}
