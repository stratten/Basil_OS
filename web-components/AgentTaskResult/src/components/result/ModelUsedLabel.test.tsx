// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelUsedLabel } from './ModelUsedLabel';
import { resetModelDisplayNameCache } from './useModelDisplayName';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const apiMocks = vi.hoisted(() => ({
  getReasoningModels: vi.fn(),
}));

vi.mock('../../services/api', () => apiMocks);

const registry = {
  models: [
    { id: 'gpt-5-mini', name: 'gpt-5-mini', display_name: 'GPT-5 mini (OpenAI)', provider: 'openai', category: 'api', is_api_model: true },
    { id: 'local-qwen-3.5', name: 'Qwen', display_name: '', provider: 'local', category: 'local', is_api_model: false },
  ],
  current_model: 'gpt-5-mini',
  api_models_enabled: true,
};

let container: HTMLDivElement | undefined;
let root: Root | undefined;

async function renderLabel(modelId: string | undefined, prefix?: string) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<ModelUsedLabel className="probe" modelId={modelId} prefix={prefix} />);
  });
  return container;
}

beforeEach(() => {
  resetModelDisplayNameCache();
  apiMocks.getReasoningModels.mockReset();
  apiMocks.getReasoningModels.mockResolvedValue(registry);
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  container = undefined;
  root = undefined;
  vi.restoreAllMocks();
});

describe('ModelUsedLabel', () => {
  it('shows the registry display name once the registry loads', async () => {
    const view = await renderLabel('gpt-5-mini');
    expect(view.querySelector('.probe')?.textContent).toBe('GPT-5 mini (OpenAI)');
    expect(view.querySelector('.probe')?.getAttribute('title')).toBe('Answered by GPT-5 mini (OpenAI)');
  });

  it('falls back to the registry name when the display name is empty', async () => {
    const view = await renderLabel('local-qwen-3.5');
    expect(view.querySelector('.probe')?.textContent).toBe('Qwen');
  });

  it('falls back to the raw id for a model missing from the registry', async () => {
    const view = await renderLabel('retired-model-9');
    expect(view.querySelector('.probe')?.textContent).toBe('retired-model-9');
  });

  it('renders nothing and never contacts the registry when no model was recorded', async () => {
    const view = await renderLabel(undefined);
    expect(view.querySelector('.probe')).toBeNull();
    expect(apiMocks.getReasoningModels).not.toHaveBeenCalled();
  });

  it('shows the raw id when the registry request fails, then recovers on a later mount', async () => {
    apiMocks.getReasoningModels.mockRejectedValueOnce(new Error('offline'));
    let view = await renderLabel('gpt-5-mini');
    expect(view.querySelector('.probe')?.textContent).toBe('gpt-5-mini');

    act(() => root?.unmount());
    view.remove();
    view = await renderLabel('gpt-5-mini');
    expect(view.querySelector('.probe')?.textContent).toBe('GPT-5 mini (OpenAI)');
  });

  it('prefixes the name when asked and shares one registry request across labels', async () => {
    const view = await renderLabel('gpt-5-mini', 'Model:');
    expect(view.querySelector('.probe')?.textContent).toBe('Model: GPT-5 mini (OpenAI)');

    const second = document.createElement('div');
    document.body.appendChild(second);
    const secondRoot = createRoot(second);
    await act(async () => {
      secondRoot.render(<ModelUsedLabel className="probe" modelId="local-qwen-3.5" />);
    });
    expect(second.querySelector('.probe')?.textContent).toBe('Qwen');
    expect(apiMocks.getReasoningModels).toHaveBeenCalledTimes(1);
    act(() => secondRoot.unmount());
    second.remove();
  });
});
