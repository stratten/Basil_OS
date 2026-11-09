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

describe('checkpoint details normalization', () => {
  it('keeps trimmed details for any input type', () => {
    const approval = normalizeCheckpointData('task-1', {
      prompt: 'Send this reply to Mariam now?',
      input_type: 'yes_no',
      details_markdown: '  **To:** mariam@example.com\n\nHi Mariam  ',
    });
    expect(approval?.input_type).toBe('confirmation');
    expect(approval?.details_markdown).toBe('**To:** mariam@example.com\n\nHi Mariam');

    const text = normalizeCheckpointData('task-1', {
      prompt: 'Any changes?',
      input_type: 'text',
      details_markdown: 'Draft body',
    });
    expect(text?.details_markdown).toBe('Draft body');
  });

  it('drops blank and non-string details', () => {
    expect(
      normalizeCheckpointData('task-1', { prompt: 'Send it?', input_type: 'yes_no', details_markdown: '   \n ' }),
    ).not.toHaveProperty('details_markdown');
    expect(
      normalizeCheckpointData('task-1', { prompt: 'Send it?', input_type: 'yes_no', details_markdown: 42 }),
    ).not.toHaveProperty('details_markdown');
    expect(normalizeCheckpointData('task-1', { prompt: 'Send it?', input_type: 'yes_no' })).not.toHaveProperty(
      'details_markdown',
    );
  });
});
