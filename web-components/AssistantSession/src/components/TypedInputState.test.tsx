import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { TypedInputState } from './TypedInputState';

describe('TypedInputState', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
  });

  it('hydrates and submits the typed-instruction draft from the native snapshot', () => {
    render(
      <TypedInputState
        state={{
          ...initialAssistantSessionState,
          inputMode: 'type',
          typedInstruction: 'Preserved draft',
          canSubmitTypedInstruction: true,
        }}
        showProgressElements={false}
        progressMessage={null}
      />,
    );

    expect(screen.getByRole('textbox')).toHaveValue('Preserved draft');
    fireEvent.click(screen.getByRole('button', { name: /^submit/i }));
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'submitTypedInstruction',
      text: 'Preserved draft',
    });
  });
});
