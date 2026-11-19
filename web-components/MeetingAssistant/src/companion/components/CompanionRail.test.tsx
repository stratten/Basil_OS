import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionRail from './CompanionRail';

describe('CompanionRail', () => {
  it('offers the History rail control, mirrored, to bring the Companion back', () => {
    const onExpand = vi.fn();
    render(<CompanionRail onExpand={onExpand} />);
    const button = screen.getByRole('button', { name: 'Show the Companion' });
    expect(button.querySelector('.companion-mirrored-symbol')).not.toBeNull();
    fireEvent.click(button);
    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it('reports what is waiting in the hidden pane, as a short count on the rail and in full to assistive technology', () => {
    render(<CompanionRail onExpand={vi.fn()} badge="3 new" />);
    expect(screen.getByRole('button', { name: 'Show the Companion, 3 new' })).toBeInTheDocument();
    expect(screen.getByText('3')).toHaveClass('companion-badge-count');
  });

  it('shows no badge when nothing is waiting', () => {
    const { container } = render(<CompanionRail onExpand={vi.fn()} />);
    expect(container.querySelector('.companion-badge-count')).toBeNull();
  });

  it('says the Companion is open in its own window and raises it, without a badge', () => {
    const onExpand = vi.fn();
    const { container } = render(<CompanionRail onExpand={onExpand} badge="3 new" detached />);
    const button = screen.getByRole('button', { name: 'The Companion is open in its own window. Bring it to front.' });
    expect(button).toHaveAttribute('title', 'The Companion is open in its own window. Bring it to front.');
    expect(container.querySelector('.companion-badge-count')).toBeNull();
    fireEvent.click(button);
    expect(onExpand).toHaveBeenCalledTimes(1);
  });
});
