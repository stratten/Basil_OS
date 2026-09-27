import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { AssistantSessionApp } from './AssistantSessionApp';

const renderCounts = vi.hoisted(() => new Map<string, number>());

vi.mock('../components/RecordingState', () => ({
  RecordingState: () => {
    renderCounts.set('RecordingState', (renderCounts.get('RecordingState') ?? 0) + 1);
    return <div data-testid="recording-state" />;
  },
}));

vi.mock('../components/TypedInputState', () => ({
  TypedInputState: () => <div data-testid="typed-input-state" />,
}));

vi.mock('../components/ProcessingState', () => ({
  ProcessingState: () => <div data-testid="processing-state" />,
}));

describe('AssistantSessionApp meter isolation', () => {
  it('does not re-render the active phase component when the meter ticks', () => {
    renderCounts.clear();
    render(<AssistantSessionApp />);
    expect(renderCounts.get('RecordingState')).toBe(1);

    act(() => {
      window.basilAssistantSession?.onEvent({ type: 'meter', audioLevel: 0.4 });
      window.basilAssistantSession?.onEvent({ type: 'meter', audioLevel: 0.7 });
    });

    expect(renderCounts.get('RecordingState')).toBe(1);
  });

  it('switches from typed input to processing when native commits submission', () => {
    render(<AssistantSessionApp />);

    act(() => {
      window.basilAssistantSession?.onEvent({
        type: 'snapshot',
        protocolVersion: 1,
        revision: 1,
        ...initialAssistantSessionState,
        hasSnapshot: true,
        inputMode: 'type',
        ocrText: 'Captured context',
        canSubmitTypedInstruction: true,
      });
    });

    expect(screen.getByTestId('typed-input-state')).toBeInTheDocument();

    act(() => {
      window.basilAssistantSession?.onEvent({
        type: 'snapshot',
        protocolVersion: 1,
        revision: 2,
        ...initialAssistantSessionState,
        hasSnapshot: true,
        inputMode: 'type',
        assistantSessionStatus: 'running',
        inputCommitted: false,
      });
    });

    expect(screen.getByTestId('processing-state')).toBeInTheDocument();
    expect(screen.queryByTestId('typed-input-state')).not.toBeInTheDocument();
  });
});
