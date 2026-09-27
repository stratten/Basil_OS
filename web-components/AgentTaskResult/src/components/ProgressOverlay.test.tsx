// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProgressOverlay from './ProgressOverlay';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ProgressOverlay presence', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
  });

  afterEach(() => vi.unstubAllGlobals());

  it('retains the latest step while its overlay exits', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(<ProgressOverlay isProcessing currentStep="Writing report" />);
    });
    act(() => {
      root.render(<ProgressOverlay isProcessing={false} />);
    });

    const overlay = container.querySelector('.progress-overlay');
    expect(overlay?.getAttribute('data-presence-phase')).toBe('exiting');
    expect(overlay?.textContent).toContain('Writing report');

    act(() => {
      overlay?.dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'opacity' }));
    });
    expect(container.querySelector('.progress-overlay')).toBeNull();

    act(() => root.unmount());
    container.remove();
  });

  it('crossfades only when the normalized step label changes', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => root.render(<ProgressOverlay isProcessing currentStep="Writing report" />));
    act(() => root.render(<ProgressOverlay isProcessing currentStep="Verifying report" />));

    const outgoing = container.querySelector('.progress-step-stack-layer[data-presence-phase="exiting"]');
    expect(outgoing?.textContent).toContain('Writing report');
    expect(container.textContent).toContain('Verifying report');

    act(() => root.unmount());
    container.remove();
  });
});
