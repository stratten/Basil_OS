import TokenizedSelect from '../../../shared/TokenizedSelect';
import MeetingSwitch from '../components/MeetingSwitch';
import type { CompanionMode } from './types';

export const ACTIVE_MODE_HELP = 'Speaks up on its own: offers suggestions when the topic shifts and from time to time, on top of answering questions and flagging the topics you watch.';
export const PASSIVE_MODE_HELP = 'Stays quiet unless prompted: answers questions asked in the conversation or in chat, and flags the topics you watch. No suggestions of its own.';

const MODE_OPTIONS = [
  { value: 'active', label: 'Active', title: ACTIVE_MODE_HELP },
  { value: 'passive', label: 'Passive', title: PASSIVE_MODE_HELP },
] as const;

export interface CompanionToggleProps {
  enabled: boolean;
  busy: boolean;
  onChange: (next: boolean) => void;
  /** The mode choice, shown to the right of the switch while the Companion is on. Omitted while the saved mode is not yet known. */
  mode?: { value: CompanionMode; onChange: (mode: CompanionMode) => void };
  /** What is waiting in the Companion pane while it is out of view ("3 new"); nothing shows when null or absent. */
  badge?: string | null;
}

/** The Companion switch, built on the same switch as Live Transcribe, with the mode select beside it once the Companion is on. Bringing a hidden pane back is the right-edge rail's job, as the history rail does on the left. */
export default function CompanionToggle({ enabled, busy, onChange, mode, badge = null }: CompanionToggleProps) {
  return (
    <div className="companion-toggle">
      <MeetingSwitch label="Companion" checked={enabled} disabled={busy} onChange={onChange} className="meeting-live-transcription-switch" />
      {enabled && mode && (
        <TokenizedSelect<CompanionMode>
          className="companion-mode-select"
          menuClassName="companion-mode-menu"
          title={mode.value === 'active' ? `Active. ${ACTIVE_MODE_HELP}` : `Passive. ${PASSIVE_MODE_HELP}`}
          value={mode.value}
          options={MODE_OPTIONS}
          ariaLabel="Companion mode"
          onValueChange={mode.onChange}
        />
      )}
      {badge && <span className="companion-badge-count" role="status">{badge}</span>}
    </div>
  );
}
