import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { ModelPickerMenu } from './ModelPickerMenu';

describe('ModelPickerMenu', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
  });

  it('requests the native menu from the voice selector', () => {
    render(
      <ModelPickerMenu
        variant="miniChevron"
        state={{
          ...initialAssistantSessionState,
          selectedModelId: 'local-1',
          localModels: [{ id: 'local-1', displayName: 'Local One', isApiModel: false }],
          apiModels: [{ id: 'api-1', displayName: 'API One', isApiModel: true }],
          useApiModels: true,
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));

    expect(postMessage).toHaveBeenCalledWith({
      type: 'showNativeModelPicker',
      models: [
        { id: 'local-1', displayName: 'Local One', isApiModel: false },
        { id: 'api-1', displayName: 'API One', isApiModel: true },
      ],
      selectedModelId: 'local-1',
      anchorRect: expect.objectContaining({
        x: expect.any(Number),
        y: expect.any(Number),
        width: expect.any(Number),
        height: expect.any(Number),
      }),
    });
  });

  it('stays enabled while audio is being captured, including refinement recording', () => {
    const models = { localModels: [{ id: 'local-1', displayName: 'Local One', isApiModel: false }] };
    const { rerender } = render(
      <ModelPickerMenu
        variant="miniChevron"
        state={{ ...initialAssistantSessionState, ...models, transcriptionStatus: 'running', isRecording: true }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Reasoning model' })).not.toBeDisabled();

    rerender(
      <ModelPickerMenu
        variant="miniChevron"
        state={{
          ...initialAssistantSessionState,
          ...models,
          assistantOutput: 'Prior output',
          isRefinementMode: true,
          transcriptionStatus: 'running',
          isRecording: true,
        }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Reasoning model' })).not.toBeDisabled();
  });

  it('locks once the request is being processed', () => {
    render(
      <ModelPickerMenu
        variant="miniChevron"
        state={{
          ...initialAssistantSessionState,
          localModels: [{ id: 'local-1', displayName: 'Local One', isApiModel: false }],
          assistantSessionStatus: 'running',
        }}
      />,
    );
    expect(screen.getByRole('button', { name: 'Reasoning model' })).toBeDisabled();
  });
});
