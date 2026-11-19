import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionFocusField, { COMPANION_FOCUS_MAX_CHARS } from './CompanionFocusField';

describe('CompanionFocusField', () => {
  it('saves the trimmed text when the field loses focus', async () => {
    const onSave = vi.fn(async () => true);
    render(<CompanionFocusField value="" onSave={onSave} />);
    const field = screen.getByLabelText('Focus (optional):');
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: '  Launch date  ' } });
    fireEvent.blur(field);
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Launch date'));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not save an unchanged value', () => {
    const onSave = vi.fn(async () => true);
    render(<CompanionFocusField value="Pricing" onSave={onSave} />);
    const field = screen.getByLabelText('Focus (optional):');
    fireEvent.focus(field);
    fireEvent.blur(field);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('explains a failed save', async () => {
    render(<CompanionFocusField value="" onSave={vi.fn(async () => false)} />);
    const field = screen.getByLabelText('Focus (optional):');
    fireEvent.change(field, { target: { value: 'x' } });
    fireEvent.blur(field);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be saved');
  });

  it('limits the text to the backend maximum', () => {
    render(<CompanionFocusField value="" onSave={vi.fn(async () => true)} />);
    expect(screen.getByLabelText('Focus (optional):')).toHaveAttribute('maxlength', String(COMPANION_FOCUS_MAX_CHARS));
  });
});
