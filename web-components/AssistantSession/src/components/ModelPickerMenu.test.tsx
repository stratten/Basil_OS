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
});
