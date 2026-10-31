import Dropdown, { type DropdownOption } from '../Dropdown';
import { chainFormError, type ChainAgeUnit, type ChainFormState } from './scheduledChainHelpers';

type ChainModeValue = 'independent' | 'chained';

const MODE_OPTIONS: DropdownOption<ChainModeValue>[] = [
  { value: 'independent', label: 'Each run is its own task' },
  { value: 'chained', label: 'Runs continue one conversation' },
];

const UNIT_OPTIONS: DropdownOption<ChainAgeUnit>[] = [
  { value: 'minutes', label: 'minutes' },
  { value: 'hours', label: 'hours' },
  { value: 'days', label: 'days' },
];

export const CHAIN_LABEL = 'Runs';

const CHAIN_HELP =
  'When runs continue one conversation, each run sees what the earlier runs did and anything you added in between, and shows up as one entry in the sidebar. A run is skipped while the previous one is still working or waiting for you. A new conversation starts after the limits you choose.';

interface Props {
  form: ChainFormState;
  onChange: (next: ChainFormState) => void;
  disabled?: boolean;
}

const rowStyle = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  fontFamily: 'var(--font-family-light)',
  fontSize: 'var(--font-size-callout)',
  color: 'var(--text-primary)',
} as const;

const labelStyle = { fontFamily: 'var(--font-family-medium)', color: 'var(--text-tertiary)', minWidth: 72, paddingTop: 4 } as const;

const checkLineStyle = { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } as const;

// The "Runs" row of the create and edit forms. Independent runs are the default and send nothing; chained runs reveal the limits that decide when a new conversation starts and whether it receives the last result.
export default function ScheduledChainField({ form, onChange, disabled }: Props) {
  const error = chainFormError(form);
  const patch = (changes: Partial<ChainFormState>) => onChange({ ...form, ...changes });
  return (
    <div style={rowStyle}>
      <span style={labelStyle} title={CHAIN_HELP}>
        {CHAIN_LABEL}
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 0 }}>
        <div style={{ maxWidth: 280 }} title={CHAIN_HELP}>
          <Dropdown
            value={form.chained ? 'chained' : 'independent'}
            options={MODE_OPTIONS}
            ariaLabel="How runs relate to each other"
            disabled={disabled}
            onChange={value => patch({ chained: value === 'chained' })}
          />
        </div>
        {form.chained && (
          <>
            <span>Start a new conversation after:</span>
            <label style={checkLineStyle}>
              <input
                type="checkbox"
                checked={form.limitRuns}
                disabled={disabled}
                onChange={event => patch({ limitRuns: event.target.checked })}
                aria-label="Limit the number of runs"
              />
              <span>This many runs</span>
              <input
                className="sidebar-search-input"
                type="number"
                min={1}
                value={form.maxRuns}
                disabled={disabled || !form.limitRuns}
                onChange={event => patch({ maxRuns: event.target.value })}
                style={{ flex: '0 0 90px' }}
                aria-label="Maximum runs in one conversation"
              />
            </label>
            <div style={checkLineStyle}>
              <input
                type="checkbox"
                checked={form.limitAge}
                disabled={disabled}
                onChange={event => patch({ limitAge: event.target.checked })}
                aria-label="Limit how long one conversation lasts"
              />
              <span>This much time since its first run</span>
              <input
                className="sidebar-search-input"
                type="number"
                min={1}
                value={form.ageValue}
                disabled={disabled || !form.limitAge}
                onChange={event => patch({ ageValue: event.target.value })}
                style={{ flex: '0 0 90px' }}
                aria-label="Maximum conversation length"
              />
              <div style={{ flex: '0 0 130px' }}>
                <Dropdown
                  value={form.ageUnit}
                  options={UNIT_OPTIONS}
                  ariaLabel="Conversation length unit"
                  disabled={disabled || !form.limitAge}
                  onChange={value => patch({ ageUnit: value })}
                />
              </div>
            </div>
            <label style={checkLineStyle}>
              <input
                type="checkbox"
                checked={form.carryOver}
                disabled={disabled}
                onChange={event => patch({ carryOver: event.target.checked })}
                aria-label="Carry the last result over to the new conversation"
              />
              <span>Give the new conversation the last result of the old one</span>
            </label>
            {error && (
              <span role="alert" style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-family-medium)' }}>
                {error}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}
