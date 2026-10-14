import TokenizedSelect from '../../../shared/TokenizedSelect';
import MeetingSwitch from '../components/MeetingSwitch';
import type { CompanionMode } from './types';

const MODE_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'passive', label: 'Passive' },
] as const;

export interface CompanionToggleProps {
  enabled: boolean;
  busy: boolean;
  onChange: (next: boolean) => void;
  /** The mode choice, shown to the right of the switch while the Companion is on. Omitted while the saved mode is not yet known. */
  mode?: { value: CompanionMode; onChange: (mode: CompanionMode) => void };
}

/** The Companion switch, built on the same switch as Live Transcribe, with the mode select beside it once the Companion is on. Bringing a hidden pane back is the right-edge rail's job, as the history rail does on the left. */
export default function CompanionToggle({ enabled, busy, onChange, mode }: CompanionToggleProps) {
  return (
    <div className="companion-toggle">
      <MeetingSwitch label="Companion" checked={enabled} disabled={busy} onChange={onChange} className="meeting-live-transcription-switch" />
      {enabled && mode && (
        <TokenizedSelect<CompanionMode>
          className="companion-mode-select"
          value={mode.value}
          options={MODE_OPTIONS}
          ariaLabel="Companion mode"
          onValueChange={mode.onChange}
        />
      )}
    </div>
  );
}
