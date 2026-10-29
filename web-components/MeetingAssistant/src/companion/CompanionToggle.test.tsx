// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CompanionToggle, { ACTIVE_MODE_HELP, PASSIVE_MODE_HELP } from './CompanionToggle';

afterEach(cleanup);

describe('Companion mode help', () => {
  it('explains each mode on hover, in the closed control and in the open list', () => {
    render(<CompanionToggle enabled busy={false} onChange={vi.fn()} mode={{ value: 'active', onChange: vi.fn() }} />);
    const trigger = screen.getByRole('button', { name: 'Companion mode' });
    expect(trigger).toHaveAttribute('title', expect.stringContaining(ACTIVE_MODE_HELP));
    fireEvent.click(trigger);
    expect(screen.getByRole('option', { name: 'Active' })).toHaveAttribute('title', ACTIVE_MODE_HELP);
    expect(screen.getByRole('option', { name: 'Passive' })).toHaveAttribute('title', PASSIVE_MODE_HELP);
    expect(document.querySelector('.tokenized-select__menu')).toHaveClass('companion-mode-menu');
  });

  it('describes the chosen mode on the closed control', () => {
    render(<CompanionToggle enabled busy={false} onChange={vi.fn()} mode={{ value: 'passive', onChange: vi.fn() }} />);
    expect(screen.getByRole('button', { name: 'Companion mode' })).toHaveAttribute('title', expect.stringContaining(PASSIVE_MODE_HELP));
  });

  it('shows no mode control while the Companion is off', () => {
    render(<CompanionToggle enabled={false} busy={false} onChange={vi.fn()} mode={{ value: 'active', onChange: vi.fn() }} />);
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
  });
});
