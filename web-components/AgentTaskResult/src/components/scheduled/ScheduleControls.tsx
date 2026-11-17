import Dropdown, { type DropdownOption } from '../Dropdown';
import ScheduledField from './ScheduledField';
import WeekdayChips from './WeekdayChips';

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
  // Optional first run of an interval schedule. A time alone means its next
  // occurrence; a date makes it that day. Both empty means "start counting from
  // when the schedule is saved".
  startDate: string;
  onStartDateChange: (v: string) => void;
  startTime: string;
  onStartTimeChange: (v: string) => void;
  // 'First run' while creating; 'Next run' when editing a schedule that already has one.
  startLabel: string;
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

// The labeled Schedule row: schedule type / mode / time-or-interval-or-runAt / timezone
// on one line, plus an optional weekday-selector line underneath that appears only
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
  startDate,
  onStartDateChange,
  startTime,
  onStartTimeChange,
  startLabel,
  runAt,
  onRunAtChange,
  timezone,
  onTimezoneChange,
  timezoneOptions,
  weeklyDays,
  onToggleWeekday,
}: Props) {
  return (
    <ScheduledField label="Schedule">
      <div className="scheduled-field__line">
        <div className="scheduled-field__grow">
          <Dropdown
            value={scheduleType}
            options={SCHEDULE_TYPE_OPTIONS}
            onChange={onScheduleTypeChange}
            ariaLabel="Schedule type"
          />
        </div>
        {scheduleType === 'recurring' && (
          <div className="scheduled-field__grow">
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
            className="scheduled-input scheduled-input--time"
            type="time"
            value={time}
            onChange={e => onTimeChange(e.target.value)}
            aria-label="Time of day"
          />
        )}
        {scheduleType === 'recurring' && mode === 'interval' && (
          <input
            className="scheduled-input scheduled-input--time"
            type="number"
            min={1}
            value={intervalMinutes}
            onChange={e => onIntervalMinutesChange(Number(e.target.value))}
            placeholder="Minutes"
            aria-label="Interval in minutes"
          />
        )}
        {scheduleType === 'one_time' && (
          <input
            className="scheduled-input scheduled-input--datetime"
            type="datetime-local"
            value={runAt}
            onChange={e => onRunAtChange(e.target.value)}
            aria-label="Run at date and time"
          />
        )}
        <div className="scheduled-field__grow scheduled-field__grow--wide">
          <Dropdown
            value={timezone}
            options={timezoneOptions}
            onChange={onTimezoneChange}
            searchable
            ariaLabel="Timezone"
          />
        </div>
      </div>

      {scheduleType === 'recurring' && mode === 'interval' && (
        <div role="group" aria-label={`${startLabel} (optional)`} className="scheduled-field__line">
          <span className="scheduled-field__sublabel">{startLabel} (optional)</span>
          <input
            className="scheduled-input scheduled-input--time"
            type="time"
            value={startTime}
            onChange={e => onStartTimeChange(e.target.value)}
            aria-label={`${startLabel} time of day`}
          />
          <input
            className="scheduled-input scheduled-input--date"
            type="date"
            value={startDate}
            onChange={e => onStartDateChange(e.target.value)}
            aria-label={`${startLabel} date (defaults to the next time that clock time comes around)`}
          />
          {(startTime || startDate) && (
            <button
              type="button"
              className="action-btn action-btn--neutral"
              onClick={() => {
                onStartTimeChange('');
                onStartDateChange('');
              }}
            >
              Clear
            </button>
          )}
          {startDate && !startTime && (
            <span role="alert" className="scheduled-error scheduled-field__full">
              Add a time for the {startLabel.toLowerCase()}, or clear the date.
            </span>
          )}
        </div>
      )}

      {scheduleType === 'recurring' && mode === 'weekly' && (
        <WeekdayChips selectedDays={weeklyDays} onToggle={onToggleWeekday} />
      )}
    </ScheduledField>
  );
}
