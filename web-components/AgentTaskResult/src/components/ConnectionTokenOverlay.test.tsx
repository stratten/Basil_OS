// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import ConnectionTokenOverlay, { nameProblem } from './ConnectionTokenOverlay';
import type { TokenConnectRequest } from '../types';

const requestTokenConnect = vi.fn();
const requestTokenConnectCancel = vi.fn();
let resultHandler: ((result: { requestId: string; status: string; message?: string }) => void) | null = null;

vi.mock('../services/bridge', () => ({
  requestTokenConnect: (...args: unknown[]) => requestTokenConnect(...args),
  requestTokenConnectCancel: (...args: unknown[]) => requestTokenConnectCancel(...args),
  registerTokenConnectResultHandler: (cb: (result: { requestId: string; status: string; message?: string }) => void) => {
    resultHandler = cb;
    return () => {
      if (resultHandler === cb) resultHandler = null;
    };
  },
}));

vi.mock('../store/agentStore', () => ({
  agentStore: {
    hideTokenConnect: vi.fn(),
  },
}));

import { agentStore } from '../store/agentStore';

let container: HTMLElement;
let root: Root;

const REQUEST: TokenConnectRequest = {
  requestId: 'r1',
  serverUrl: 'https://huggingface.co/mcp',
  host: 'huggingface.co',
  friendlyName: 'Hugging Face',
  description: 'Suggested note',
  existingNames: ['Linear'],
};

function setInput(label: string, value: string) {
  const input = container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function render(request: TokenConnectRequest = REQUEST) {
  act(() => {
    root.render(<ConnectionTokenOverlay agentTaskId="task-1" request={request} />);
  });
}

describe('ConnectionTokenOverlay', () => {
  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    requestTokenConnect.mockReset();
    requestTokenConnectCancel.mockReset();
    vi.mocked(agentStore.hideTokenConnect).mockReset();
    resultHandler = null;
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('uses the Paprika overlay card and names the destination host', () => {
    render();
    expect(container.querySelector('.overlay-backdrop')).not.toBeNull();
    expect(container.querySelector('.overlay-card')).not.toBeNull();
    expect(container.textContent).toContain('huggingface.co');
    expect(container.textContent).toContain('https://huggingface.co/mcp');
    expect((container.querySelector('input[aria-label="Connection name"]') as HTMLInputElement).value).toBe('Hugging Face');
    expect((container.querySelector('input[aria-label="Connection description"]') as HTMLInputElement).value).toBe('Suggested note');
    expect((container.querySelector('button.action-btn.success') as HTMLButtonElement).disabled).toBe(true);
  });

  it('sends the edited name and description with the token', () => {
    render();
    act(() => {
      setInput('Connection name', '  Hugging Face (infra)  ');
      setInput('Connection description', '  Write access for model inventory  ');
      setInput('Token or API key', 'hf_abc');
    });
    act(() => {
      (container.querySelector('button.action-btn.success') as HTMLButtonElement).click();
    });
    expect(requestTokenConnect).toHaveBeenCalledWith({
      requestId: 'r1',
      friendlyName: 'Hugging Face (infra)',
      description: 'Write access for model inventory',
      token: 'hf_abc',
    });
  });

  it('refuses a name that is already used', () => {
    render({ ...REQUEST, existingNames: ['Hugging Face', 'Linear'], alreadyConnectedAs: 'Hugging Face' });
    expect(container.textContent).toContain('You already have Hugging Face connected');
    act(() => setInput('Token or API key', 'hf_abc'));
    expect((container.querySelector('button.action-btn.success') as HTMLButtonElement).disabled).toBe(true);
    act(() => {
      (container.querySelector('button.action-btn.success') as HTMLButtonElement).click();
    });
    expect(requestTokenConnect).not.toHaveBeenCalled();
  });

  it('keeps the overlay open when the app reports a failed check', () => {
    render();
    act(() => setInput('Token or API key', 'hf_abc'));
    act(() => {
      (container.querySelector('button.action-btn.success') as HTMLButtonElement).click();
    });
    act(() => {
      resultHandler?.({ requestId: 'r1', status: 'failed', message: 'The service rejected the token.' });
    });
    expect(agentStore.hideTokenConnect).not.toHaveBeenCalled();
    expect(container.textContent).toContain('The service rejected the token.');
    expect((container.querySelector('button.action-btn.success') as HTMLButtonElement).disabled).toBe(false);
  });

  it('Cancel does not send a token', () => {
    render();
    act(() => setInput('Token or API key', 'hf_abc'));
    act(() => {
      (container.querySelector('button.action-btn.danger') as HTMLButtonElement).click();
    });
    expect(requestTokenConnectCancel).toHaveBeenCalledWith('r1');
    expect(requestTokenConnect).not.toHaveBeenCalled();
  });
});

describe('nameProblem', () => {
  it('rejects a blank, overlong, or reused name', () => {
    expect(nameProblem('   ', [])).toBe('Give this connection a name.');
    expect(nameProblem('n'.repeat(81), [])).toMatch(/80/);
    expect(nameProblem('Hugging Face', ['Hugging Face'])).toMatch(/already exists/);
    expect(nameProblem('Hugging Face (work)', ['Hugging Face'])).toBeNull();
  });
});
