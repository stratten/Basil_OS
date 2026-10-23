import { useCallback, useEffect, useRef, useState } from 'react';
import type { MeetingUIStateDTO } from '../bridge/types';
import type { AudioSourceCompanionProps } from '../components/AudioSourceControls';
import { COMPANION_PANE_WIDTH, COMPANION_RAIL_WIDTH, COMPANION_TRANSITION_MS } from './companionLayout';
import { companionHasContent, shouldShowCompanionPane } from './companionPaneState';
import { selectCompanionStream } from './companionStreamSelectors';
import { useCompanionView } from './companionViewStore';
import { companionPort } from './companionTarget';
import type { CompanionMode } from './types';
import { useCompanionGlobalSettings } from './useCompanionGlobalSettings';
import { useCompanionSwitch } from './useCompanionSwitch';
import { awarenessBadgeText, useCompanionAwareness } from './useCompanionUnseen';
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
  const awareness = useCompanionAwareness(meetingId, companion.state);
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const [armBusy, setArmBusy] = useState(false);
  const [armError, setArmError] = useState<string | null>(null);

  // A different meeting starts with its own pane open. The one exception is the meeting that begins from the setup pane: a pane the reader already tucked into the rail stays there, and an open one stays open, so starting the meeting never changes the width on its own.
  const previousMeetingId = useRef(meetingId);
  useEffect(() => {
    const meetingChanged = previousMeetingId.current !== meetingId;
    previousMeetingId.current = meetingId;
    setDismissedFor((current) => {
      if (current === SETUP_PANE_KEY && isRecording && meetingId !== null) return meetingId;
      return meetingChanged ? null : current;
    });
  }, [meetingId, isRecording]);

  // The backend hands the pre-recording focus to the meeting that starts and then clears it, so reload the saved settings when a recording begins.
  const { refresh: refreshGlobalSettings } = globalSettings;
  useEffect(() => {
    if (isRecording) void refreshGlobalSettings();
  }, [isRecording, refreshGlobalSettings]);

  const isIdle = !isRecording && !ui?.isViewingPastMeeting;
  const isArmed = globalSettings.settings?.auto_enable === true;
  const setupAvailable = isIdle && isArmed;
  // The moment recording starts the setup pane is showing, but the new meeting's Companion has not loaded yet, so it cannot say it is on. Keep the column as it was until it has loaded; otherwise the width would drop to nothing and open again a moment later.
  const previousKind = useRef<CompanionPaneKind | null>(null);
  const carriedFromSetup = useRef(false);
  const meetingLoading = companion.state.phase === 'idle' || companion.state.phase === 'loading';
  const holdColumnOpen = isRecording && meetingLoading && (previousKind.current === 'setup' || carriedFromSetup.current);
  const recordingAvailable =
    !setupAvailable &&
    (holdColumnOpen ||
      shouldShowCompanionPane({
        meetingId,
        dismissedFor: null,
        isEnabled: companion.isEnabled,
        hasContent: companionHasContent(companion.state.timeline),
      }));
  const kind: CompanionPaneKind | null = setupAvailable ? 'setup' : recordingAvailable ? 'recording' : null;
  // Until the meeting's id is known, a recording pane that took over from setup still answers to the setup pane's dismissal.
  const dismissalKey = kind === 'setup' || meetingId === null ? SETUP_PANE_KEY : meetingId;
  // While the detached Companion window is open the Companion lives there, so the column folds to a rail that raises it. The reader's own dismissal is untouched, so closing that window restores the column exactly as it was.
  const detached = kind !== null && ui?.isCompanionWindowOpen === true;
  // The detached window showed everything that arrived while the column was folded, so when it closes that backlog is not "new" here: the restored column starts from the latest row, as if the reader had been looking at it.
  const { markSeen } = useCompanionView(meetingId, null);
  const wasDetached = useRef(false);
  const latestTimeline = useRef(companion.state.timeline);
  latestTimeline.current = companion.state.timeline;
  useEffect(() => {
    const restored = wasDetached.current && !detached;
    wasDetached.current = detached;
    if (!restored) return;
    let latestSeq = -1;
    for (const entry of selectCompanionStream(latestTimeline.current)) {
      if (entry.seq !== null && entry.seq > latestSeq) latestSeq = entry.seq;
    }
    if (latestSeq >= 0) markSeen(latestSeq);
  }, [detached, markSeen]);
  const expanded = kind !== null && !detached && dismissedFor !== dismissalKey;
  const hasRail = kind !== null && !expanded;
  const extent = expanded ? COMPANION_PANE_WIDTH : hasRail ? COMPANION_RAIL_WIDTH : 0;
  useEffect(() => {
    previousKind.current = kind;
    carriedFromSetup.current = holdColumnOpen;
  });

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

  // The pane reports its own unseen rows once it is open; the badge exists for the time it is hidden.
  const hiddenBadge = expanded ? null : awarenessBadgeText(awareness);
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
        badge: isRecording ? hiddenBadge : null,
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
    /** The Companion is open in its own window; the rail brings that window to the front. */
    detached,
    extent,
    /** What arrived while the pane is hidden, for the rail. */
    hiddenBadge,
    switchProps,
    hidePane: () => {
      if (!detached) setDismissedFor(dismissalKey);
    },
    showPane: () => setDismissedFor(null),
  };
}
