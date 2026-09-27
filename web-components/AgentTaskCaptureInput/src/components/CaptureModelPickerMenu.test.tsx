// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CaptureModelPickerMenu from './CaptureModelPickerMenu';
import { getReasoningModels } from '../services/api';

vi.mock('../services/api', () => ({
  getReasoningModels: vi.fn(),
  isApiReady: () => true,
}));

vi.mock('../../../shared/ReasoningModelPicker', () => ({
  default: ({
    ariaLabel,
    onRequestNativeMenu,
  }: {
    ariaLabel: string;
    onRequestNativeMenu?: (anchorRect: DOMRect) => void;
  }) => (
    <button
      aria-label={ariaLabel}
      onClick={(event) => onRequestNativeMenu?.(event.currentTarget.getBoundingClientRect())}
    >
      Model
    </button>
  ),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

describe('CaptureModelPickerMenu', () => {
  it('selects the backend current model after loading', async () => {
    vi.mocked(getReasoningModels).mockResolvedValue({
      models: [{
        id: 'local-model',
        name: 'local-model',
        display_name: 'Local Model',
        provider: 'local',
        category: 'local',
        is_api_model: false,
      }],
      current_model: 'local-model',
      api_models_enabled: true,
    });
    const onModelChange = vi.fn();

    await act(async () => {
      root.render(<CaptureModelPickerMenu disabled={false} selectedModelId={null} onModelChange={onModelChange} />);
    });

    expect(onModelChange).toHaveBeenCalledWith('local-model');
    expect(container.querySelector('.capture-model-picker__error')).toBeNull();
  });

  it('requests the native menu from the compact voice trigger', async () => {
    const model = {
      id: 'local-model',
      name: 'local-model',
      display_name: 'Local Model',
      provider: 'local',
      category: 'local' as const,
      is_api_model: false,
    };
    vi.mocked(getReasoningModels).mockResolvedValue({
      models: [model],
      current_model: 'local-model',
      api_models_enabled: true,
    });
    const onRequestNativeMenu = vi.fn();

    await act(async () => {
      root.render(
        <CaptureModelPickerMenu
          disabled={false}
          selectedModelId="local-model"
          onModelChange={() => {}}
          onRequestNativeMenu={onRequestNativeMenu}
        />
      );
    });

    const trigger = container.querySelector('[aria-label="Reasoning model"]') as HTMLButtonElement;
    const anchorRect = trigger.getBoundingClientRect();
    act(() => trigger.click());

    expect(onRequestNativeMenu).toHaveBeenCalledWith([model], 'local-model', anchorRect);
  });

  it('renders a visible unavailable state when model loading fails', async () => {
    vi.mocked(getReasoningModels).mockRejectedValue(new Error('offline'));
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    await act(async () => {
      root.render(<CaptureModelPickerMenu disabled={false} selectedModelId={null} onModelChange={() => {}} />);
    });

    expect(consoleError).toHaveBeenCalled();
    expect(container.querySelector('.capture-model-picker__error')?.textContent).toBe('Models unavailable');
    expect(container.querySelector('[aria-label="Models unavailable"]')).not.toBeNull();
  });
});
