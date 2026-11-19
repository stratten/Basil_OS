// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ExpandableClamp from './ExpandableClamp';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let transitionDuration = '0.5s';
let frameHeight = 60;
let contentScrollHeight = 200;
let frameAnimations: unknown[] = [];

function render(expanded: boolean) {
  act(() => {
    root.render(
      <ExpandableClamp expanded={expanded}>
        <p>Long transcript text</p>
      </ExpandableClamp>,
    );
  });
}

const frame = () => container.querySelector<HTMLDivElement>('.basil-expandable-clamp')!;
const content = () => container.querySelector<HTMLDivElement>('.basil-expandable-clamp__content')!;

function endHeightTransition() {
  const event = new Event('transitionend', { bubbles: true });
  Object.assign(event, { propertyName: 'height' });
  act(() => {
    frame().dispatchEvent(event);
  });
}

beforeEach(() => {
  transitionDuration = '0.5s';
  frameHeight = 60;
  contentScrollHeight = 200;
  frameAnimations = [{}];
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.spyOn(window, 'getComputedStyle').mockImplementation(
    () => ({ transitionDuration, transitionDelay: '0s', lineHeight: '20px' }) as unknown as CSSStyleDeclaration,
  );
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => frameHeight });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => contentScrollHeight });
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', { configurable: true, value: () => frameAnimations });
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

describe('ExpandableClamp', () => {
  it('starts clamped with no explicit height and applies no animation on mount', () => {
    render(false);
    expect(content().classList.contains('is-clamped')).toBe(true);
    expect(frame().style.height).toBe('');
  });

  it('starts unclamped when mounted expanded', () => {
    render(true);
    expect(content().classList.contains('is-clamped')).toBe(false);
  });

  it('expands by lifting the clamp and transitioning the frame to the full height, then releases the height', () => {
    render(false);
    render(true);
    expect(content().classList.contains('is-clamped')).toBe(false);
    expect(frame().style.height).toBe('200px');
    endHeightTransition();
    expect(frame().style.height).toBe('');
    expect(content().classList.contains('is-clamped')).toBe(false);
  });

  it('collapses to the clamped height and restores the clamp only after the transition ends', () => {
    render(true);
    frameHeight = 200;
    render(false);
    expect(content().classList.contains('is-clamped')).toBe(false);
    expect(frame().style.height).toBe('60px');
    endHeightTransition();
    expect(content().classList.contains('is-clamped')).toBe(true);
    expect(frame().style.height).toBe('');
  });

  it('ignores transitionend for properties other than height', () => {
    render(true);
    frameHeight = 200;
    render(false);
    const event = new Event('transitionend', { bubbles: true });
    Object.assign(event, { propertyName: 'opacity' });
    act(() => {
      frame().dispatchEvent(event);
    });
    expect(content().classList.contains('is-clamped')).toBe(false);
  });

  it('settles immediately without a transition when motion is disabled', () => {
    transitionDuration = '0s';
    render(true);
    frameHeight = 200;
    render(false);
    expect(content().classList.contains('is-clamped')).toBe(true);
    expect(frame().style.height).toBe('');
  });

  it('does not animate when the text is shorter than the clamp', () => {
    contentScrollHeight = 40;
    frameHeight = 40;
    transitionDuration = '0s';
    render(false);
    render(true);
    expect(frame().style.height).toBe('');
    render(false);
    expect(content().classList.contains('is-clamped')).toBe(true);
  });
});
