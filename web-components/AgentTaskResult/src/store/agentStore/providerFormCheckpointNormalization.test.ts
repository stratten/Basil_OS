import { describe, expect, it } from 'vitest';
import { normalizeCheckpointData } from './checkpointNormalization';

describe('normalizeCheckpointData provider_form handling', () => {
  it('keeps an empty target-authorization choice as a choice for clarification', () => {
    const normalized = normalizeCheckpointData('task-1', {
      checkpoint_id: 'authorization-1',
      prompt: 'Which target should Basil use?',
      input_type: 'choice',
      options: [],
      metadata: {
        source: 'provider_target_authorization',
        authorization_id: 'authorization-1',
        cancel_value: 'target-cancel:1',
      },
    });

    expect(normalized?.input_type).toBe('choice');
    expect(normalized?.options).toBeUndefined();
  });

  it('normalizes a multi-field provider form with text and choice fields', () => {
    const normalized = normalizeCheckpointData('task-1', {
      checkpoint_id: 'interaction-1',
      prompt: 'Pick a strategy and describe why.',
      input_type: 'provider_form',
      fields: [
        {
          name: 'strategy',
          label: 'Strategy',
          kind: 'choice',
          required: true,
          options: [
            { id: 'strategy-option-0', label: 'balanced', value: 'balanced' },
            { id: 'strategy-option-1', label: 'aggressive', value: 'aggressive' },
          ],
        },
        { name: 'rationale', label: 'Rationale', kind: 'text', required: false },
      ],
      metadata: { source: 'provider_user_input', provider_run_id: 'run-1' },
    });

    expect(normalized?.input_type).toBe('provider_form');
    expect(normalized?.fields).toHaveLength(2);
    expect(normalized?.fields?.[0]).toMatchObject({ name: 'strategy', kind: 'choice', required: true });
    expect(normalized?.fields?.[0].options).toHaveLength(2);
    expect(normalized?.fields?.[1]).toMatchObject({ name: 'rationale', kind: 'text', required: false });
  });

  it('degrades to a free-text prompt when a choice field has no usable options', () => {
    const normalized = normalizeCheckpointData('task-1', {
      checkpoint_id: 'interaction-2',
      prompt: 'Pick a strategy.',
      input_type: 'provider_form',
      fields: [{ name: 'strategy', label: 'Strategy', kind: 'choice', required: true, options: [] }],
      metadata: { source: 'provider_user_input' },
    });

    expect(normalized?.input_type).toBe('data');
    expect(normalized?.fields).toBeUndefined();
  });

  it('degrades to a free-text prompt when fields is missing entirely', () => {
    const normalized = normalizeCheckpointData('task-1', {
      checkpoint_id: 'interaction-3',
      prompt: 'Provider needs input.',
      input_type: 'provider_form',
      metadata: { source: 'provider_user_input' },
    });

    expect(normalized?.input_type).toBe('data');
    expect(normalized?.fields).toBeUndefined();
  });

  it('drops a field with a blank name rather than rendering it incorrectly', () => {
    const normalized = normalizeCheckpointData('task-1', {
      checkpoint_id: 'interaction-4',
      prompt: 'Pick a strategy.',
      input_type: 'provider_form',
      fields: [
        { name: '', label: 'Blank', kind: 'text', required: false },
        { name: 'strategy', label: 'Strategy', kind: 'text', required: true },
      ],
      metadata: { source: 'provider_user_input' },
    });

    expect(normalized?.fields).toHaveLength(1);
    expect(normalized?.fields?.[0].name).toBe('strategy');
  });
});
