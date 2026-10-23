import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { ResultState } from './ResultState';

describe('ResultState', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
  });

  it('sends the locally applied text when save follows the native edit-mode transition', () => {
    const editingState = {
      ...initialAssistantSessionState,
      assistantSessionStatus: 'completed' as const,
      assistantOutput: 'Original output',
      editableContentSeed: 'Original output',
      isEditMode: true,
      shouldPersistUI: true,
    };
    const { rerender } = render(<ResultState state={editingState} />);

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Edited output' } });
    fireEvent.click(screen.getByRole('button', { name: /apply edits/i }));

    rerender(<ResultState state={{ ...editingState, isEditMode: false }} />);
    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));

    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'saveAsSample',
      content: 'Edited output',
    });
  });

  it('keeps a terminal stream error visible alongside partial output', () => {
    render(
      <ResultState
        state={{
          ...initialAssistantSessionState,
          assistantSessionStatus: 'failed',
          assistantOutput: 'Partial output',
          errorMessage: 'Provider failed',
          shouldPersistUI: true,
        }}
      />,
    );

    expect(screen.getByText('Provider failed')).toBeInTheDocument();
    expect(screen.getByText('Partial output')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save as sample/i })).not.toBeInTheDocument();
  });

  it('notifies the resize owner when typed refinement opens', () => {
    const onTypedRefinementModeChange = vi.fn();
    render(
      <ResultState
        state={{
          ...initialAssistantSessionState,
          assistantSessionStatus: 'completed',
          assistantOutput: 'Original output',
          shouldPersistUI: true,
        }}
        onTypedRefinementModeChange={onTypedRefinementModeChange}
      />,
    );

    fireEvent.click(screen.getByTitle('Type additional instructions to refine this output'));

    expect(onTypedRefinementModeChange).toHaveBeenCalledWith(true);
  });

  it('clears parent typed-refinement layout state when processing starts', () => {
    const onTypedRefinementModeChange = vi.fn();
    const state = {
      ...initialAssistantSessionState,
      assistantSessionStatus: 'completed' as const,
      assistantOutput: 'Original output',
      shouldPersistUI: true,
    };
    const { rerender } = render(
      <ResultState state={state} onTypedRefinementModeChange={onTypedRefinementModeChange} />,
    );

    rerender(
      <ResultState
        state={{ ...state, assistantSessionStatus: 'running' }}
        onTypedRefinementModeChange={onTypedRefinementModeChange}
      />,
    );

    expect(onTypedRefinementModeChange).toHaveBeenCalledWith(false);
  });

  it('keeps the refinement indicator visible while voice refinement is recording', () => {
    render(
      <ResultState
        state={{
          ...initialAssistantSessionState,
          assistantSessionStatus: 'completed',
          assistantOutput: 'Original output',
          isRefinementMode: true,
          isRecording: true,
          iterationCount: 1,
          showRefinementIndicator: true,
          shouldPersistUI: true,
        }}
      />,
    );

    expect(screen.getByRole('button', { name: /stop recording/i })).toBeInTheDocument();
    expect(screen.getByText('Refinement Mode')).toBeInTheDocument();
    expect(screen.getByText('(Iteration 1)')).toBeInTheDocument();
  });
});
