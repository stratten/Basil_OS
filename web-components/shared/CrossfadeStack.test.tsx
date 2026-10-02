// @vitest-environment jsdom

import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CrossfadeStack from './CrossfadeStack';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

function Counter({ label }: { label: string }) {
  const [count, setCount] = useState(0);
  return (
    <button type="button" data-label={label} onClick={() => setCount((value) => value + 1)}>
      {`${label}:${count}`}
    </button>
  );
}

function renderStack(contentKey: string, settleWithoutTransition = false) {
  act(() => {
    root.render(
      <CrossfadeStack
        contentKey={contentKey}
        className="stack basil-crossfade"
        layerClassName="basil-crossfade-layer"
        settleWithoutTransition={settleWithoutTransition}
      >
        <Counter label={contentKey} />
      </CrossfadeStack>,
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
  vi.unstubAllGlobals();
});

describe('CrossfadeStack', () => {
  it('applies an explicit layer class name', () => {
    renderStack('a');
    expect(container.querySelectorAll('.basil-crossfade-layer')).toHaveLength(1);
    expect(container.querySelector('.stack-layer')).toBeNull();
  });

  it('keeps the incoming layer instance after the outgoing layer completes', () => {
    renderStack('a');
    renderStack('b');
    const layers = container.querySelectorAll<HTMLElement>('.basil-crossfade-layer');
    expect(layers).toHaveLength(2);
    expect(layers[0].getAttribute('data-presence-phase')).toBe('exiting');

    const incoming = container.querySelector<HTMLButtonElement>('button[data-label="b"]')!;
    act(() => incoming.click());
    expect(incoming.textContent).toBe('b:1');

    act(() => {
      layers[0].dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'opacity' }));
    });
    expect(container.querySelectorAll('.basil-crossfade-layer')).toHaveLength(1);
    expect(container.querySelector('button[data-label="b"]')).toBe(incoming);
    expect(incoming.textContent).toBe('b:1');
  });

  it('removes the outgoing layer immediately when it has no CSS transition', () => {
    renderStack('a', true);
    renderStack('b', true);
    expect(container.querySelectorAll('.basil-crossfade-layer')).toHaveLength(1);
    expect(container.textContent).toBe('b:0');
  });
});
