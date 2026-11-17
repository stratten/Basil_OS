import type { ExclusionWindow } from '../../types';
import ScheduledField from './ScheduledField';
import WeekdayChips from './WeekdayChips';
import {
  MAX_EXCLUSION_WINDOWS,
  exclusionWindowsError,
  newExclusionWindow,
  toggleWindowDay,
} from './scheduledChainHelpers';

export const EXCLUSIONS_LABEL = 'Quiet hours';

const EXCLUSIONS_HELP =
  'The schedule does not run during these times, read in the schedule timezone. A window that ends earlier than it starts crosses midnight. The weekdays you pick are the days the window starts on; with none picked it applies every day.';

interface Props {
  windows: ExclusionWindow[];
  onChange: (next: ExclusionWindow[]) => void;
  disabled?: boolean;
}

// The "Quiet hours" row of the create and edit forms: any number of daily windows, up to eight, in which a recurring schedule does not start a run. Each window has a start, an end, and optionally the weekdays it starts on.
export default function ScheduledExclusionWindowsField({ windows, onChange, disabled }: Props) {
  const error = exclusionWindowsError(windows);
  const update = (index: number, next: ExclusionWindow) => onChange(windows.map((entry, i) => (i === index ? next : entry)));
  return (
    <ScheduledField label={EXCLUSIONS_LABEL} help={EXCLUSIONS_HELP}>
      {windows.map((window, index) => {
        const days = window.days ?? [];
        return (
          <div key={index} role="group" aria-label={`Quiet hours window ${index + 1}`} className="scheduled-window">
            <div className="scheduled-window__line">
              <span>Do not run from</span>
              <input
                className="scheduled-input scheduled-input--time"
                type="time"
                value={window.start}
                disabled={disabled}
                onChange={event => update(index, { ...window, start: event.target.value })}
                aria-label={`Quiet hours ${index + 1} start`}
              />
              <span>until</span>
              <input
                className="scheduled-input scheduled-input--time"
                type="time"
                value={window.end}
                disabled={disabled}
                onChange={event => update(index, { ...window, end: event.target.value })}
                aria-label={`Quiet hours ${index + 1} end`}
              />
              <button
                type="button"
                className="scheduled-icon-btn"
                disabled={disabled}
                onClick={() => onChange(windows.filter((_, i) => i !== index))}
                aria-label={`Remove quiet hours window ${index + 1}`}
                title="Remove this window"
              >
                ×
              </button>
            </div>
            <WeekdayChips
              compact
              selectedDays={days}
              disabled={disabled}
              onToggle={day => update(index, toggleWindowDay(window, day))}
              ariaLabelFor={label => `${label} for quiet hours window ${index + 1}`}
            />
            <span className="scheduled-hint">{days.length > 0 ? 'Starting on the selected days only.' : 'Every day.'}</span>
          </div>
        );
      })}
      <button
        type="button"
        className="scheduled-link-btn"
        disabled={disabled || windows.length >= MAX_EXCLUSION_WINDOWS}
        onClick={() => onChange([...windows, newExclusionWindow()])}
      >
        Add quiet hours
      </button>
      {error && (
        <span role="alert" className="scheduled-error">
          {error}
        </span>
      )}
    </ScheduledField>
  );
}
