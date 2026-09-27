// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import {
  __resetCaptureMeterForTests,
  publishCaptureMeter,
  useCaptureMeter,
} from './captureMeterStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root | undefined;
let container: HTMLDivElement | undefined;

function MeterValue() {
  return <output>{useCaptureMeter()}</output>;
}

function renderMeter() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(<MeterValue />);
  });
}

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
  __resetCaptureMeterForTests();
});

describe('captureMeterStore', () => {
  it('starts at zero and publishes changed levels', () => {
    renderMeter();
    expect(container?.textContent).toBe('0');

    act(() => {
      publishCaptureMeter(0.6);
    });

    expect(container?.textContent).toBe('0.6');
  });

  it('clamps levels to the supported range', () => {
    renderMeter();

    act(() => {
      publishCaptureMeter(1.5);
    });
    expect(container?.textContent).toBe('1');

    act(() => {
      publishCaptureMeter(-1);
    });
    expect(container?.textContent).toBe('0');
  });

  it('does not re-render for an unchanged clamped level', () => {
    let renders = 0;
    function RenderCounter() {
      renders++;
      useCaptureMeter();
      return null;
    }

    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root!.render(<RenderCounter />);
    });
    act(() => {
      publishCaptureMeter(0.3);
    });
    const afterChange = renders;

    act(() => {
      publishCaptureMeter(0.3);
    });

    expect(renders).toBe(afterChange);
  });
});
