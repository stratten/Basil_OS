import Dropdown, { type DropdownOption } from '../Dropdown';
import { WEEKDAY_LABELS } from './scheduledAgentTaskHelpers';

export type ScheduleType = 'one_time' | 'recurring';
export type RecurringMode = 'daily' | 'weekly' | 'interval';

interface Props {
  scheduleType: ScheduleType;
  onScheduleTypeChange: (v: ScheduleType) => void;
  mode: RecurringMode;
  onModeChange: (v: RecurringMode) => void;
  // HH:MM (24h) for the daily/weekly recurring modes.
  time: string;
  onTimeChange: (v: string) => void;
  intervalMinutes: number;
  onIntervalMinutesChange: (n: number) => void;
  // datetime-local value (YYYY-MM-DDTHH:MM) for the one-time mode.
  runAt: string;
  onRunAtChange: (v: string) => void;
  timezone: string;
  onTimezoneChange: (v: string) => void;
  timezoneOptions: DropdownOption<string>[];
  // 0..6 (Sun..Sat) selected days for weekly mode.
  weeklyDays: number[];
  onToggleWeekday: (idx: number) => void;
}

// Static, schema-defined option lists. Deliberately at module scope rather
// than as props: they never vary per call site, and inlining them inside
// the component would re-allocate on every render and force consumers
// (Dropdown's memoization) to treat them as new each time.
const SCHEDULE_TYPE_OPTIONS: DropdownOption<ScheduleType>[] = [
  { value: 'recurring', label: 'Recurring' },
  { value: 'one_time', label: 'One-time' },
];

const MODE_OPTIONS: DropdownOption<RecurringMode>[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'interval', label: 'Every N minutes' },
];

// Single-row schedule type / mode / time-or-interval-or-runAt / timezone
// row, plus an optional weekday-selector row underneath that appears only
// when the user has chosen a recurring weekly schedule. Used identically
// inside both the create form and the inline-edit form in
// ScheduledAgentTaskDetail; consolidating both call sites here means the
// two paths can no longer drift in styling, ordering, or which inputs are
// shown for each mode.
export default function ScheduleControls({
  scheduleType,
  onScheduleTypeChange,
  mode,
  onModeChange,
  time,
  onTimeChange,
  intervalMinutes,
  onIntervalMinutesChange,
  runAt,
  onRunAtChange,
  timezone,
  onTimezoneChange,
  timezoneOptions,
  weeklyDays,
  onToggleWeekday,
}: Props) {
  return (
    <>
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'stretch',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 130px', minWidth: 130 }}>
          <Dropdown
            value={scheduleType}
            options={SCHEDULE_TYPE_OPTIONS}
            onChange={onScheduleTypeChange}
            ariaLabel="Schedule type"
          />
        </div>
        {scheduleType === 'recurring' && (
          <div style={{ flex: '1 1 150px', minWidth: 150 }}>
            <Dropdown
              value={mode}
              options={MODE_OPTIONS}
              onChange={onModeChange}
              ariaLabel="Recurring mode"
            />
          </div>
        )}
        {scheduleType === 'recurring' && mode !== 'interval' && (
          <input
            className="sidebar-search-input schedule-time-input"
            type="time"
            value={time}
            onChange={e => onTimeChange(e.target.value)}
            style={{ flex: '0 0 110px' }}
            aria-label="Time of day"
          />
        )}
        {scheduleType === 'recurring' && mode === 'interval' && (
          <input
            className="sidebar-search-input"
            type="number"
            min={1}
            value={intervalMinutes}
            onChange={e => onIntervalMinutesChange(Number(e.target.value))}
            placeholder="Minutes"
            style={{ flex: '0 0 110px' }}
            aria-label="Interval in minutes"
          />
        )}
        {scheduleType === 'one_time' && (
          <input
            className="sidebar-search-input schedule-time-input"
            type="datetime-local"
            value={runAt}
            onChange={e => onRunAtChange(e.target.value)}
            style={{ flex: '1 1 200px', minWidth: 200 }}
            aria-label="Run at date and time"
          />
        )}
        <div style={{ flex: '1 1 200px', minWidth: 180 }}>
          <Dropdown
            value={timezone}
            options={timezoneOptions}
            onChange={onTimezoneChange}
            searchable
            ariaLabel="Timezone"
          />
        </div>
      </div>

      {scheduleType === 'recurring' && mode === 'weekly' && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {WEEKDAY_LABELS.map((label, idx) => {
            const selected = weeklyDays.includes(idx);
            return (
              <button
                key={label}
                type="button"
                onClick={() => onToggleWeekday(idx)}
                aria-pressed={selected}
                style={{
                  flex: '1 1 0',
                  minWidth: 44,
                  padding: '6px 8px',
                  border: '1px solid var(--separator-color)',
                  borderRadius: 'var(--corner-radius-small)',
                  background: selected ? 'rgba(51, 85, 155, 0.85)' : 'var(--background-tertiary)',
                  color: selected ? 'white' : 'var(--text-primary)',
                  fontFamily: 'var(--font-family-medium)',
                  fontSize: 'var(--font-size-status-small)',
                  cursor: 'pointer',
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
    </>
  );
}
