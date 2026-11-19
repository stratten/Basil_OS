import { Switch } from '@shared/inputs/Switch';
import Dropdown, { type DropdownOption } from '../Dropdown';
import ScheduledField from './ScheduledField';
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
  'When runs continue one conversation, each run sees what the earlier runs did and anything you added in between, and shows up as one entry in the sidebar. A run is skipped while the previous one is still working or waiting for you. A new conversation starts after the limits you choose. The turn limit counts every turn in the conversation, including follow-ups you type and follow-ups Basil starts itself, so a conversation you keep adding to starts over sooner.';

const CHECKLIST_HELP =
  'Each run keeps a checklist of its steps. When this is on, the open and waiting items from the schedule\'s previous run, and its notes, are copied into the next run as carried items. Done and dropped items stay behind. Leave it off for a clean slate every run.';

interface Props {
  form: ChainFormState;
  onChange: (next: ChainFormState) => void;
  disabled?: boolean;
}

// The "Runs" row of the create and edit forms. Independent runs are the default and send nothing; chained runs reveal the limits that decide when a new conversation starts and whether it receives the last result.
export default function ScheduledChainField({ form, onChange, disabled }: Props) {
  const error = chainFormError(form);
  const patch = (changes: Partial<ChainFormState>) => onChange({ ...form, ...changes });
  return (
    <ScheduledField label={CHAIN_LABEL} help={CHAIN_HELP}>
      <div className="scheduled-field__limit" title={CHAIN_HELP}>
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
          <span className="scheduled-field__sublabel">Start a new conversation after:</span>
          <div className="scheduled-switch-row">
            <Switch
              checked={form.limitRuns}
              disabled={disabled}
              onChange={checked => patch({ limitRuns: checked })}
              label="This many turns, including your follow-ups"
              ariaLabel="Limit the number of turns"
            />
            <input
              className="scheduled-input scheduled-input--count"
              type="number"
              min={1}
              value={form.maxRuns}
              disabled={disabled || !form.limitRuns}
              onChange={event => patch({ maxRuns: event.target.value })}
              aria-label="Maximum turns in one conversation"
            />
          </div>
          <div className="scheduled-switch-row">
            <Switch
              checked={form.limitAge}
              disabled={disabled}
              onChange={checked => patch({ limitAge: checked })}
              label="This much time since its first run"
              ariaLabel="Limit how long one conversation lasts"
            />
            <input
              className="scheduled-input scheduled-input--count"
              type="number"
              min={1}
              value={form.ageValue}
              disabled={disabled || !form.limitAge}
              onChange={event => patch({ ageValue: event.target.value })}
              aria-label="Maximum conversation length"
            />
            <div className="scheduled-field__unit">
              <Dropdown
                value={form.ageUnit}
                options={UNIT_OPTIONS}
                ariaLabel="Conversation length unit"
                disabled={disabled || !form.limitAge}
                onChange={value => patch({ ageUnit: value })}
              />
            </div>
          </div>
          <Switch
            checked={form.carryOver}
            disabled={disabled}
            onChange={checked => patch({ carryOver: checked })}
            label="Give the new conversation the last result of the old one"
            ariaLabel="Carry the last result over to the new conversation"
          />
          {error && (
            <span role="alert" className="scheduled-error">
              {error}
            </span>
          )}
        </>
      )}
      <div title={CHECKLIST_HELP}>
        <Switch
          checked={form.carryChecklist}
          disabled={disabled}
          onChange={checked => patch({ carryChecklist: checked })}
          label="Carry unfinished checklist items over to the next run"
          ariaLabel="Carry unfinished checklist items over to the next run"
        />
      </div>
    </ScheduledField>
  );
}
