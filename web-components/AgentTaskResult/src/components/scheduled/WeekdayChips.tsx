import { WEEKDAY_LABELS } from './scheduledAgentTaskHelpers';

interface Props {
  /** Selected days, Monday as 0 through Sunday as 6. */
  selectedDays: readonly number[];
  onToggle: (day: number) => void;
  disabled?: boolean;
  /** The smaller chip used inside a quiet-hours window. */
  compact?: boolean;
  /** Accessible name for one chip, from its short label; defaults to the label itself. */
  ariaLabelFor?: (label: string) => string;
}

/** The seven weekday toggles, shared by the weekly schedule picker and every quiet-hours window. */
export default function WeekdayChips({ selectedDays, onToggle, disabled, compact, ariaLabelFor }: Props) {
  return (
    <div className="scheduled-weekdays">
      {WEEKDAY_LABELS.map((label, day) => {
        const selected = selectedDays.includes(day);
        const className = ['scheduled-weekday', compact ? 'scheduled-weekday--compact' : '', selected ? 'is-selected' : ''].filter(Boolean).join(' ');
        return (
          <button
            key={label}
            type="button"
            className={className}
            disabled={disabled}
            onClick={() => onToggle(day)}
            aria-pressed={selected}
            aria-label={ariaLabelFor ? ariaLabelFor(label) : undefined}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
