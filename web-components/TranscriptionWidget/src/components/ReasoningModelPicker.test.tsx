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

  it('disables the trigger while busy and keeps the model label', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} busy onModelChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveTextContent('Local Model');
  });

  it('keeps the chevron and no label in miniChevron+busy', () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} busy variant="miniChevron" onModelChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).toBeDisabled();
    expect(trigger).not.toHaveTextContent('Local Model');
    expect(trigger).toHaveClass('rich-text-model-picker-trigger--mini-chevron');
  });

  it('calls onModelChange with the selected id when an option is chosen', async () => {
    const onModelChange = vi.fn();
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} onModelChange={onModelChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    await userEvent.click(screen.getByRole('option', { name: 'API Model' }));
    expect(onModelChange).toHaveBeenCalledWith('api-1');
  });
  it('offers no clear entry unless clearOptionLabel is supplied', async () => {
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} onModelChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Local Model', 'API Model']);
  });

  it('adds a first clear entry that selects nothing when clearOptionLabel is supplied', async () => {
    const onModelChange = vi.fn();
    render(<ReasoningModelPicker models={models} selectedModelId="local-1" disabled={false} clearOptionLabel="Default model" onModelChange={onModelChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    const options = screen.getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['Default model', 'Local Model', 'API Model']);
    expect(options[0]).toHaveAttribute('aria-selected', 'false');
    await userEvent.click(options[0]);
    expect(onModelChange).toHaveBeenCalledWith(undefined);
  });

  it('shows the clear label and marks the clear entry selected while nothing is selected', async () => {
    render(<ReasoningModelPicker models={models} disabled={false} clearOptionLabel="Default model" onModelChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: 'Reasoning model' });
    expect(trigger).toHaveTextContent('Default model');
    await userEvent.click(trigger);
    expect(screen.getByRole('option', { name: 'Default model' })).toHaveAttribute('aria-selected', 'true');
  });

  it('moves through the clear entry and the models with the arrow keys', async () => {
    render(<ReasoningModelPicker models={models} disabled={false} clearOptionLabel="Default model" onModelChange={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
    const options = screen.getAllByRole('option');
    options[0].focus();
    await userEvent.keyboard('{ArrowDown}');
    expect(options[1]).toHaveFocus();
    await userEvent.keyboard('{ArrowUp}{ArrowUp}');
    expect(options[2]).toHaveFocus();
  });
});
