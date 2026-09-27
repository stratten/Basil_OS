import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';

const models = [
  { id: 'local-1', name: 'Local Model', category: 'local' as const },
  { id: 'api-1', name: 'API Model', category: 'api' as const },
];

describe('ReasoningModelPicker', () => {
  it('renders the default trigger with the selected model label', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} onModelChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Reasoning model' })).toHaveTextContent('Local Model');
  });

  it('renders a bare chevron with no label in miniChevron variant', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} onModelChange={vi.fn()} variant="miniChevron" />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).not.toHaveTextContent('Local Model');
    expect(trigger).toHaveClass('rich-text-model-picker-trigger--mini-chevron');
  });

  it('disables the trigger and shows a spinner while busy, regardless of the disabled prop', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} busy onModelChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent('Switching…');
  });

  it('shows a bare spinner with no text in miniChevron+busy', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} busy variant="miniChevron" onModelChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).not.toHaveTextContent('Switching…');
  });

  it('calls onModelChange with the selected id when an option is chosen', async () => {
    const onModelChange = vi.fn();
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} onModelChange={onModelChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    await userEvent.click(screen.getByRole('option', { name: 'API Model' }));
    expect(onModelChange).toHaveBeenCalledWith('api-1');
  });
});
