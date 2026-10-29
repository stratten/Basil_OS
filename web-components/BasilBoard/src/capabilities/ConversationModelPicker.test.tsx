import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationModelPicker from './ConversationModelPicker';

const models = [
  { id: 'local-qwen', name: 'local-qwen', display_name: 'Qwen Local', provider: 'qwen', category: 'local' as const, is_api_model: false },
  { id: 'api-gpt', name: 'api-gpt', display_name: 'GPT API', provider: 'openai', category: 'api' as const, is_api_model: true },
  { id: 'custom-lab', name: 'custom-lab', display_name: 'Lab Model', provider: 'custom', category: 'custom' as const, is_api_model: true },
];

describe('ConversationModelPicker', () => {
  it('groups canonical models and reports the selected model', async () => {
    const onModelChange = vi.fn();
    render(
      <ConversationModelPicker
        models={models}
        selectedModelId="local-qwen"
        disabled={false}
        onModelChange={onModelChange}
      />,
    );

    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger.textContent).toContain('Qwen Local');
    await userEvent.click(trigger);
    expect(screen.getByRole('group', { name: 'Local Models' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'API Models' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Custom Models' })).toBeTruthy();
    await userEvent.click(screen.getByRole('option', { name: 'Lab Model' }));
    expect(onModelChange).toHaveBeenCalledWith('custom-lab');
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('closes the listbox with Escape', async () => {
    render(
      <ConversationModelPicker
        models={models}
        selectedModelId="local-qwen"
        disabled={false}
        onModelChange={vi.fn()}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    await userEvent.click(trigger);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
