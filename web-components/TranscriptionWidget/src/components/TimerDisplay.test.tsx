import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TimerDisplay } from './TimerDisplay';

describe('TimerDisplay', () => {
  it('formats sub-minute seconds with a leading zero', () => {
    render(<TimerDisplay seconds={7} />);
    expect(screen.getByText('0:07')).toBeInTheDocument();
  });

  it('formats minutes and seconds', () => {
    render(<TimerDisplay seconds={125} />);
    expect(screen.getByText('2:05')).toBeInTheDocument();
  });

  it('clamps negative input to zero', () => {
    render(<TimerDisplay seconds={-4} />);
    expect(screen.getByText('0:00')).toBeInTheDocument();
  });

  it('applies the compact class when requested', () => {
    render(<TimerDisplay seconds={0} compact />);
    expect(screen.getByText('0:00')).toHaveClass('transcription-timer--compact');
  });
});
