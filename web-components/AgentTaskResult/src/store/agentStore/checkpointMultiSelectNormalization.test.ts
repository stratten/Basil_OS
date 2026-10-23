import { describe, expect, it } from 'vitest';
import { normalizeCheckpointData } from './checkpointNormalization';

describe('checkpoint multi-select and numeric normalization', () => {
  it('keeps allow_multiple for selection prompts', () => {
    const normalized = normalizeCheckpointData('task-1', {
      prompt: 'Which reports?',
      input_type: 'selection',
      options: ['Sales', 'Support'],
      allow_multiple: true,
    });
    expect(normalized?.input_type).toBe('choice');
    expect(normalized?.allow_multiple).toBe(true);
  });

  it('drops allow_multiple for non-choice prompts and non-boolean values', () => {
    expect(
      normalizeCheckpointData('task-1', { prompt: 'Send it?', input_type: 'yes_no', allow_multiple: true }),
    ).not.toHaveProperty('allow_multiple');
    expect(
      normalizeCheckpointData('task-1', {
        prompt: 'Which?',
        input_type: 'selection',
        options: ['A'],
        allow_multiple: 'true',
      }),
    ).not.toHaveProperty('allow_multiple');
  });

  it('marks numeric prompts and leaves text prompts unmarked', () => {
    const numeric = normalizeCheckpointData('task-1', { prompt: 'How many?', input_type: 'numeric' });
    expect(numeric?.input_type).toBe('data');
    expect(numeric?.value_kind).toBe('numeric');
    expect(normalizeCheckpointData('task-1', { prompt: 'Notes?', input_type: 'text' })).not.toHaveProperty('value_kind');
  });
});
