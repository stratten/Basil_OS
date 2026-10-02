// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PresenceRegion from './PresenceRegion';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

function renderRegion(visible: boolean, settleWithoutTransition: boolean) {
  act(() => {
    root.render(
      <PresenceRegion visible={visible} className="region" role="presentation" settleWithoutTransition={settleWithoutTransition}>
        <span>Region content</span>
      </PresenceRegion>,
    );
  });
}

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('PresenceRegion', () => {
  it('renders the role and retains inert content while a transitioned exit is pending', () => {
    renderRegion(true, false);
    expect(container.querySelector('.region')?.getAttribute('role')).toBe('presentation');

    renderRegion(false, false);
    const region = container.querySelector('.region');
    expect(region?.getAttribute('data-presence-phase')).toBe('exiting');
    expect(region?.hasAttribute('inert')).toBe(true);
    expect(region?.textContent).toBe('Region content');
  });

  it('settles immediately when the region has no CSS transition', () => {
    renderRegion(true, true);
    renderRegion(false, true);
    expect(container.querySelector('.region')).toBeNull();
  });

  it('waits for its own transitionend when the region declares a transition', () => {
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transitionDuration: '0.18s', transitionDelay: '0s' } as CSSStyleDeclaration);
    renderRegion(true, true);
    renderRegion(false, true);
    const region = container.querySelector<HTMLElement>('.region')!;
    expect(region.getAttribute('data-presence-phase')).toBe('exiting');

    act(() => {
      region.dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'opacity' }));
    });
    expect(container.querySelector('.region')).toBeNull();
  });
});
