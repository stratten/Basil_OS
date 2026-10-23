// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  BACKEND_DISCONNECTED_MESSAGE,
  BACKEND_STALE_MESSAGE,
  BackendLivenessBanner,
  BackendLivenessNotice,
} from './BackendLivenessBanner';
import type { BackendLivenessSource } from './useBackendLiveness';
import type { BackendLivenessState } from './websocket/reconnectingWebSocket';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

class FakeSource implements BackendLivenessSource {
  private handlers: Array<(state: BackendLivenessState) => void> = [];
  state: BackendLivenessState = 'connecting';

  subscribeLiveness(handler: (state: BackendLivenessState) => void): () => void {
    this.handlers.push(handler);
    handler(this.state);
    return () => {
      this.handlers = this.handlers.filter((item) => item !== handler);
    };
  }

  emit(state: BackendLivenessState): void {
    this.state = state;
    for (const handler of this.handlers) handler(state);
  }

  get subscriberCount(): number {
    return this.handlers.length;
  }
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function alert(): HTMLElement | null {
  return container.querySelector('[role="alert"]');
}

describe('BackendLivenessNotice', () => {
  it('renders nothing while connecting or live', () => {
    act(() => root.render(<BackendLivenessNotice liveness="connecting" />));
    expect(container.innerHTML).toBe('');
    act(() => root.render(<BackendLivenessNotice liveness="live" />));
    expect(container.innerHTML).toBe('');
  });

  it('renders a labeled alert for stale and disconnected states', () => {
    act(() => root.render(<BackendLivenessNotice liveness="stale" />));
    expect(alert()?.textContent).toContain(BACKEND_STALE_MESSAGE);
    expect(alert()?.getAttribute('data-liveness')).toBe('stale');

    act(() => root.render(<BackendLivenessNotice liveness="disconnected" />));
    expect(alert()?.textContent).toContain(BACKEND_DISCONNECTED_MESSAGE);
    expect(alert()?.getAttribute('data-liveness')).toBe('disconnected');
  });
});

describe('BackendLivenessBanner', () => {
  it('follows the source and unsubscribes on unmount', () => {
    const source = new FakeSource();
    act(() => root.render(<BackendLivenessBanner socket={source} />));
    expect(alert()).toBeNull();

    act(() => source.emit('stale'));
    expect(alert()?.textContent).toContain(BACKEND_STALE_MESSAGE);

    act(() => source.emit('live'));
    expect(alert()).toBeNull();

    act(() => source.emit('disconnected'));
    expect(alert()?.textContent).toContain(BACKEND_DISCONNECTED_MESSAGE);

    act(() => root.unmount());
    expect(source.subscriberCount).toBe(0);
    root = createRoot(container);
  });
});
