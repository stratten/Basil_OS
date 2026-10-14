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
});
