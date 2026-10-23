import type { CheckpointOption } from '../types';

export interface CheckpointAnswerInput {
  selectedValues: string[];
  otherText: string;
  labeled: boolean;
}

// The request_user_input description and the agent system prompt document this exact `Selected:` / `Other:` reply format; change all three together.
export function formatCheckpointAnswer({ selectedValues, otherText, labeled }: CheckpointAnswerInput): string {
  const values = selectedValues.map(value => value.trim()).filter(value => value.length > 0);
  const other = otherText.trim();
  if (!labeled) {
    return values[0] ?? other;
  }
  if (values.length === 1 && !other) {
    return values[0];
  }
  const lines: string[] = [];
  if (values.length > 0) {
    lines.push(`Selected: ${values.join('; ')}`);
  }
  if (other) {
    lines.push(`Other: ${other}`);
  }
  return lines.join('\n');
}

export function toggleCheckpointSelection(current: string[], value: string, allowMultiple: boolean): string[] {
  if (!allowMultiple) {
    return [value];
  }
  return current.includes(value)
    ? current.filter(selected => selected !== value)
    : [...current, value];
}

export function orderSelectedValues(options: CheckpointOption[], selectedValues: string[]): string[] {
  const optionOrder = options.map(option => option.value);
  const known = optionOrder.filter(value => selectedValues.includes(value));
  const unknown = selectedValues.filter(value => !optionOrder.includes(value));
  return [...known, ...unknown];
}

const NUMERIC_ANSWER = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

export function isValidNumericAnswer(value: string): boolean {
  return NUMERIC_ANSWER.test(value.trim().replace(/,/g, ''));
}
