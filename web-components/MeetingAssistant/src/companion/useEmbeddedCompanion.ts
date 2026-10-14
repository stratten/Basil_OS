import { useCallback, useEffect, useState } from 'react';
import type { MeetingUIStateDTO } from '../bridge/types';
import type { AudioSourceCompanionProps } from '../components/AudioSourceControls';
import { COMPANION_PANE_WIDTH, COMPANION_RAIL_WIDTH, COMPANION_TRANSITION_MS } from './companionLayout';
import { companionHasContent, shouldShowCompanionPane } from './companionPaneState';
import { companionPort } from './companionTarget';
import type { CompanionMode } from './types';
import { useCompanionGlobalSettings } from './useCompanionGlobalSettings';
import { useCompanionSwitch } from './useCompanionSwitch';
import { useMeetingCompanion } from './useMeetingCompanion';

/** Dismissal key for the pre-recording setup pane, which belongs to no meeting. */
const SETUP_PANE_KEY = 'companion-setup';

const SAVE_FAILED_MESSAGE = 'The Companion setting could not be saved. Check that the Basil backend is running.';

export type CompanionPaneKind = 'setup' | 'recording';

/**
 * Everything the Notetaker window needs from the Companion: the live controller, the shared global settings, the switch beside the audio source picker, and the right-edge sidebar state.
 *
 * Before a recording starts (and while no past meeting is open) the switch arms the Companion for the next recording through the global `auto_enable` setting, so sources, mode and focus can be prepared in advance. While recording it turns the Companion on or off for the live meeting.
 *
 * The sidebar has three states, like the History sidebar: expanded, collapsed to a rail (the user hid it), and absent (nothing to show). `extent` is the width the column currently occupies, which the host window grows by.
 */
export function useEmbeddedCompanion(ui: MeetingUIStateDTO | null) {
  const { companion, meetingId, isRecording } = useMeetingCompanion(ui);
  const globalSettings = useCompanionGlobalSettings(companionPort(ui));
  const companionSwitch = useCompanionSwitch(companion);
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const [armBusy, setArmBusy] = useState(false);
  const [armError, setArmError] = useState<string | null>(null);

  useEffect(() => {
    setDismissedFor(null);
  }, [meetingId]);

  // The backend hands the pre-recording focus to the meeting that starts and then clears it, so reload the saved settings when a recording begins.
  const { refresh: refreshGlobalSettings } = globalSettings;
  useEffect(() => {
    if (isRecording) void refreshGlobalSettings();
  }, [isRecording, refreshGlobalSettings]);

  const isIdle = !isRecording && !ui?.isViewingPastMeeting;
  const isArmed = globalSettings.settings?.auto_enable === true;
  const setupAvailable = isIdle && isArmed;
  const recordingAvailable =
    !setupAvailable &&
    shouldShowCompanionPane({
      meetingId,
      dismissedFor: null,
      isEnabled: companion.isEnabled,
      hasContent: companionHasContent(companion.state.timeline),
    });
  const kind: CompanionPaneKind | null = setupAvailable ? 'setup' : recordingAvailable ? 'recording' : null;
  const dismissalKey = kind === 'setup' ? SETUP_PANE_KEY : meetingId;
  const expanded = kind !== null && dismissedFor !== dismissalKey;
  const hasRail = kind !== null && !expanded;
  const extent = expanded ? COMPANION_PANE_WIDTH : hasRail ? COMPANION_RAIL_WIDTH : 0;

  // Keep the departing pane's content mounted until the width transition finishes, so switching the Companion off does not blank it mid-animation.
  const [retainedKind, setRetainedKind] = useState<CompanionPaneKind | null>(kind);
  useEffect(() => {
    if (kind !== null) {
      setRetainedKind(kind);
      return undefined;
    }
    const timer = setTimeout(() => setRetainedKind(null), COMPANION_TRANSITION_MS + 50);
    return () => clearTimeout(timer);
  }, [kind]);

  const { update } = globalSettings;
  const arm = useCallback(
    async (next: boolean) => {
      setArmBusy(true);
      const saved = await update({ auto_enable: next });
      setArmBusy(false);
      if (!saved) setArmError(SAVE_FAILED_MESSAGE);
    },
    [update],
  );

  const showSwitch = isRecording || isIdle;
  const switchProps: AudioSourceCompanionProps | undefined = showSwitch
    ? {
        enabled: isRecording ? companion.isEnabled : isArmed,
        busy: isRecording ? companionSwitch.busy : armBusy,
        mode: isRecording
          ? { value: companion.state.status.mode, onChange: (mode: CompanionMode) => void companion.setMode(mode) }
          : globalSettings.settings
            ? { value: globalSettings.settings.default_mode, onChange: (mode: CompanionMode) => void update({ default_mode: mode }) }
            : undefined,
        onChange: (next: boolean) => {
          setDismissedFor(null);
          setArmError(null);
          if (isRecording) companionSwitch.change(next);
          else void arm(next);
        },
        error: armError ?? (expanded ? null : companion.actionError),
        onDismissError: () => {
          setArmError(null);
          companion.clearActionError();
        },
      }
    : undefined;

  return {
    companion,
    globalSettings,
    isRecording,
    kind,
    renderedKind: kind ?? retainedKind,
    expanded,
    hasRail,
    extent,
    switchProps,
    hidePane: () => setDismissedFor(dismissalKey),
    showPane: () => setDismissedFor(null),
  };
}
