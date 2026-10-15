import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionInvestigationNotice from './CompanionInvestigationNotice';

describe('CompanionInvestigationNotice', () => {
  it('renders nothing while no investigation is running', () => {
    const { container } = render(<CompanionInvestigationNotice running={0} question={null} onStop={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('names the question and stops on request', () => {
    const onStop = vi.fn(async () => true);
    render(<CompanionInvestigationNotice running={1} question="When does the contract renew?" onStop={onStop} />);
    expect(screen.getByRole('status')).toHaveTextContent('Investigating: When does the contract renew?');
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('counts several running investigations and works without a known question', () => {
    render(<CompanionInvestigationNotice running={2} question={null} onStop={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Investigating 2 questions');
  });
});
