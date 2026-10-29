import { readFileSync } from 'node:fs';
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installBlueprintReveal, WINDOW_VISIBILITY_EVENT } from '@shared/blueprintController';
import { BLUEPRINT_DRAW_MS } from '@shared/blueprintOverlay';
import { HOST_THEME_APPLIED_ATTRIBUTE } from '@shared/hostThemeSignal';
import type { Blueprint } from '@shared/blueprintMeasure';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { AssistantSessionApp } from './AssistantSessionApp';

const measure = vi.hoisted(() => vi.fn());

vi.mock('@shared/blueprintMeasure', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@shared/blueprintMeasure')>()),
  measureBlueprint: measure,
}));

const { revision: _revision, hasSnapshot: _hasSnapshot, theme: _theme, ...basePayload } = initialAssistantSessionState;

const SAMPLE: Blueprint = {
  width: 300,
  height: 138,
  rects: [{ x: 12, y: 40, width: 100, height: 24, radius: 6 }],
  lines: [{ x1: 20, x2: 120, y: 20 }],
  frame: { x: 4, y: 4, width: 292, height: 132, radius: 16 },
};

type BlueprintWindow = Window & { basilBlueprintReveal?: boolean };

let uninstall: (() => void) | null = null;

/** The host reports the window going out of sight or coming back with this event; the page-level controller handles it. */
function reportVisibility(visible: boolean, blueprintReveal: boolean) {
  act(() => {
    window.dispatchEvent(new CustomEvent(WINDOW_VISIBILITY_EVENT, { detail: { visible, blueprintReveal } }));
  });
}

/** The native side sets the flag before the page's scripts run, and the entry point installs the reveal before React renders. */
function installBeforeRender(requested: boolean) {
  (window as BlueprintWindow).basilBlueprintReveal = requested;
  uninstall = installBlueprintReveal();
}

function sendSnapshot() {
  act(() => {
    window.basilAssistantSession?.onEvent({ type: 'snapshot', protocolVersion: 1, revision: 1, ...basePayload });
  });
}

/** jsdom has no layout, so the frame is given the size the widget asks its window for while it is recording. */
function sizeFrame(container: HTMLElement, width = 260, height = 120) {
  const frame = container.querySelector('.basil-webkit-window-frame')!;
  Object.defineProperty(frame, 'offsetWidth', { configurable: true, value: width });
  Object.defineProperty(frame, 'offsetHeight', { configurable: true, value: height });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  measure.mockReset();
  measure.mockReturnValue(SAMPLE);
});

afterEach(() => {
  uninstall?.();
  uninstall = null;
  document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
  vi.useRealTimers();
  delete (window as BlueprintWindow).basilBlueprintReveal;
});

describe('AssistantSessionApp blueprint reveal', () => {
  it('does not touch the widget when the host did not ask for it', async () => {
    installBeforeRender(false);
    const { container } = render(<AssistantSessionApp />);
    sendSnapshot();
    await advance(3000);

    const frame = container.querySelector('.basil-webkit-window-frame')!;
    expect(frame.hasAttribute('data-basil-blueprint')).toBe(false);
    expect(container.querySelector('.basil-blueprint')).toBeNull();
    expect(measure).not.toHaveBeenCalled();
  });

  it('hides the widget from its first render, draws a blueprint inside the frame once it has a snapshot, then fades it in', async () => {
    installBeforeRender(true);
    const { container } = render(<AssistantSessionApp />);
    sizeFrame(container);
    const frame = container.querySelector('.basil-webkit-window-frame')!;
    const shell = container.querySelector('.assistant-session-shell')!;
    // The controller hides the frame in a mutation callback, which the browser runs before the first paint.
    await advance(0);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'hidden');

    await advance(500);
    expect(measure).not.toHaveBeenCalled();
    expect(frame).toHaveAttribute('data-basil-blueprint', 'hidden');

    sendSnapshot();
    await advance(400);
    expect(measure).toHaveBeenCalledWith(frame, shell);
    const overlay = container.querySelector('svg.basil-blueprint');
    expect(overlay).not.toBeNull();
    expect(overlay?.parentElement).toBe(frame);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'hidden');

    await advance(BLUEPRINT_DRAW_MS);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'reveal');
  });

  it('holds the widget hidden while its window is out of sight and plays the blueprint again when it comes back', async () => {
    installBeforeRender(true);
    const { container } = render(<AssistantSessionApp />);
    sizeFrame(container);
    const frame = container.querySelector('.basil-webkit-window-frame')!;
    sendSnapshot();
    await advance(400);
    await advance(BLUEPRINT_DRAW_MS);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'reveal');

    reportVisibility(false, true);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'hidden');
    expect(container.querySelector('.basil-blueprint')).toBeNull();

    reportVisibility(true, true);
    await advance(400);
    expect(container.querySelector('svg.basil-blueprint')).not.toBeNull();
    expect(frame).toHaveAttribute('data-basil-blueprint', 'hidden');

    await advance(BLUEPRINT_DRAW_MS);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'reveal');
  });

  it('plays the blueprint on a later appearance even when the widget opened with the effect off', async () => {
    installBeforeRender(false);
    const { container } = render(<AssistantSessionApp />);
    sizeFrame(container);
    const frame = container.querySelector('.basil-webkit-window-frame')!;
    sendSnapshot();
    await advance(400);
    expect(frame.hasAttribute('data-basil-blueprint')).toBe(false);

    reportVisibility(false, true);
    reportVisibility(true, true);
    await advance(400);
    expect(container.querySelector('svg.basil-blueprint')).not.toBeNull();
    await advance(BLUEPRINT_DRAW_MS);
    expect(frame).toHaveAttribute('data-basil-blueprint', 'reveal');
  });

  it('waits for the window to finish resizing to the size the widget asks for before it measures, so the drawing is not cut off', async () => {
    installBeforeRender(true);
    const { container } = render(<AssistantSessionApp />);
    sizeFrame(container, 300, 138);
    sendSnapshot();
    await advance(300);
    expect(measure).not.toHaveBeenCalled();

    sizeFrame(container, 260, 120);
    await advance(200);
    expect(measure).toHaveBeenCalled();
    expect(container.querySelector('svg.basil-blueprint')).not.toBeNull();
  });

  it('shows the widget normally when it cannot be measured', async () => {
    installBeforeRender(true);
    measure.mockReturnValue(null);
    const { container } = render(<AssistantSessionApp />);
    sendSnapshot();
    await advance(2500);

    const frame = container.querySelector('.basil-webkit-window-frame')!;
    expect(frame).toHaveAttribute('data-basil-blueprint', 'reveal');
    expect(container.querySelector('.basil-blueprint')).toBeNull();
  });
});

describe('blueprint reveal stylesheet', () => {
  const css = readFileSync('../shared/blueprint-reveal.css', 'utf8');

  it('holds back and fades in the metallic sheen layer, which the surface finish adds inside the frame, together with the rest of the window chrome', () => {
    expect(css).toContain('html[data-surface-finish] .basil-webkit-window-frame[data-basil-blueprint="hidden"] > .basil-surface-finish-overlay {\n  opacity: 0;');
    expect(css).toContain('html[data-surface-finish] .basil-webkit-window-frame[data-basil-blueprint="reveal"] > .basil-surface-finish-overlay {\n  animation: basil-blueprint-sheen-in');
    expect(css).toContain('@keyframes basil-blueprint-sheen-in {\n  from {\n    opacity: 0;\n  }\n}');
  });

  it('names the same overlay class the surface finish creates', () => {
    expect(readFileSync('../shared/surfaceFinish.ts', 'utf8')).toContain("const SURFACE_OVERLAY_CLASS = 'basil-surface-finish-overlay';");
  });
});
