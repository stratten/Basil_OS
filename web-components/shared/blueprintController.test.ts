// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Blueprint } from './blueprintMeasure';
import {
  BLUEPRINT_FRAME_ATTRIBUTE,
  BLUEPRINT_PENDING_ATTRIBUTE,
  WINDOW_VISIBILITY_EVENT,
  blueprintRevealRequested,
  installBlueprintReveal,
  setBlueprintExpectedSize,
} from './blueprintController';
import { BLUEPRINT_DRAW_MS, BLUEPRINT_WARM_DRAW_MS } from './blueprintOverlay';
import { HOST_THEME_APPLIED_ATTRIBUTE, markHostThemeApplied } from './hostThemeSignal';

const measure = vi.hoisted(() => vi.fn());
const measureOutlineOnly = vi.hoisted(() => vi.fn());

vi.mock('./blueprintMeasure', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./blueprintMeasure')>()),
  measureBlueprint: measure,
  measureOutline: measureOutlineOnly,
}));

const SAMPLE: Blueprint = {
  width: 300,
  height: 140,
  rects: [
    { x: 10, y: 10, width: 60, height: 24, radius: 4 },
    { x: 10, y: 100, width: 60, height: 24, radius: 4 },
  ],
  lines: [{ x1: 80, x2: 200, y: 50 }],
  frame: { x: 4, y: 4, width: 292, height: 132, radius: 16 },
};

type BlueprintWindow = Window & { basilBlueprintReveal?: boolean };

let uninstall: (() => void) | null = null;

function requestReveal(requested: boolean) {
  (window as BlueprintWindow).basilBlueprintReveal = requested;
}

function install(options?: Parameters<typeof installBlueprintReveal>[0]) {
  uninstall = installBlueprintReveal(options);
}

/** Mounts a window frame with a surface inside, the way every surface's React tree renders one. */
function mountFrame(extraClass = '', withSurface = true): HTMLElement {
  const frame = document.createElement('div');
  frame.className = `basil-webkit-window-frame ${extraClass}`.trim();
  if (withSurface) {
    const surface = document.createElement('div');
    surface.className = 'basil-webkit-window-surface';
    surface.textContent = 'content';
    frame.appendChild(surface);
  }
  document.body.appendChild(frame);
  return frame;
}

function stateOf(frame: HTMLElement): string | null {
  return frame.getAttribute(BLUEPRINT_FRAME_ATTRIBUTE);
}

function overlayIn(frame: HTMLElement): SVGSVGElement | null {
  return frame.querySelector('svg.basil-blueprint');
}

function sizeFrame(frame: HTMLElement, width: number, height: number) {
  Object.defineProperty(frame, 'offsetWidth', { configurable: true, value: width });
  Object.defineProperty(frame, 'offsetHeight', { configurable: true, value: height });
}

function reportVisibility(visible: boolean, blueprintReveal: boolean) {
  window.dispatchEvent(new CustomEvent(WINDOW_VISIBILITY_EVENT, { detail: { visible, blueprintReveal } }));
}

async function advance(ms: number) {
  await vi.advanceTimersByTimeAsync(ms);
}

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: reduced && query.includes('prefers-reduced-motion'), media: query, addEventListener() {}, removeEventListener() {} }));
}

beforeEach(() => {
  vi.useFakeTimers();
  measure.mockReset();
  measure.mockReturnValue(SAMPLE);
  measureOutlineOnly.mockReset();
  measureOutlineOnly.mockReturnValue(null);
  stubReducedMotion(false);
  setBlueprintExpectedSize(null);
  markHostThemeApplied();
});

afterEach(() => {
  uninstall?.();
  uninstall = null;
  document.body.innerHTML = '';
  document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
  delete (window as BlueprintWindow).basilBlueprintReveal;
  setBlueprintExpectedSize(null);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('installBlueprintReveal', () => {
  it('does nothing when the host did not ask for the reveal', async () => {
    requestReveal(false);
    install();
    const frame = mountFrame();
    await advance(5000);

    expect(stateOf(frame)).toBeNull();
    expect(overlayIn(frame)).toBeNull();
    expect(measure).not.toHaveBeenCalled();
  });

  it('hides the window from the moment its frame appears, draws the blueprint, then fades everything in', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    await advance(0);
    expect(stateOf(frame)).toBe('hidden');

    await advance(400);
    expect(stateOf(frame)).toBe('hidden');
    expect(overlayIn(frame)).not.toBeNull();
    // The window's own outline plus its two boxes and one line of text.
    expect(frame.querySelectorAll('.basil-blueprint__shape')).toHaveLength(4);

    await advance(BLUEPRINT_DRAW_MS);
    expect(stateOf(frame)).toBe('reveal');
  });

  it('hides a frame that is already in the page when it is installed', async () => {
    requestReveal(true);
    const frame = mountFrame();
    install();
    expect(stateOf(frame)).toBe('hidden');
    await advance(400);
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('draws the window outline first, before any of its parts', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    await advance(400);

    const outline = frame.querySelector('.basil-blueprint__shape') as SVGRectElement;
    expect(outline.getAttribute('x')).toBe('4');
    expect(outline.getAttribute('width')).toBe('292');
    expect(outline.getAttribute('rx')).toBe('16');
    expect(outline.style.getPropertyValue('--bp-delay')).toBe('0s');
  });

  it('starts drawing within about a tenth of a second of the surface being ready, with no polling lag', async () => {
    requestReveal(true);
    document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
    install();
    const frame = mountFrame();
    await advance(777);
    expect(overlayIn(frame)).toBeNull();

    markHostThemeApplied();
    await advance(100);
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('keeps the window hidden and measures nothing until the host theme is applied', async () => {
    requestReveal(true);
    document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
    install();
    const frame = mountFrame();
    await advance(1000);

    expect(stateOf(frame)).toBe('hidden');
    expect(measure).not.toHaveBeenCalled();
  });

  it('waits while the surface marks itself as pending and measures as soon as it is not', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    frame.setAttribute(BLUEPRINT_PENDING_ATTRIBUTE, 'true');
    await advance(1000);
    expect(measure).not.toHaveBeenCalled();
    expect(stateOf(frame)).toBe('hidden');

    frame.removeAttribute(BLUEPRINT_PENDING_ATTRIBUTE);
    await advance(100);
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('waits while anything matching the entry\'s own not-ready selector is in the surface', async () => {
    requestReveal(true);
    install({ notReadySelector: '.loading-shell' });
    const frame = mountFrame();
    const shell = document.createElement('div');
    shell.className = 'loading-shell';
    frame.firstElementChild!.appendChild(shell);
    await advance(1000);
    expect(measure).not.toHaveBeenCalled();

    shell.remove();
    await advance(150);
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('waits for the content to stop changing before it measures', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    const surface = frame.firstElementChild as HTMLElement;
    for (let step = 0; step < 6; step += 1) {
      surface.appendChild(document.createElement('span'));
      await advance(30);
    }
    expect(measure).not.toHaveBeenCalled();

    await advance(100);
    expect(measure).toHaveBeenCalled();
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('measures anyway when the content never stops changing', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    const surface = frame.firstElementChild as HTMLElement;
    for (let step = 0; step < 20; step += 1) {
      surface.appendChild(document.createElement('span'));
      await advance(30);
    }
    expect(measure).toHaveBeenCalled();
  });

  it('is not held up by its own drawing', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    await advance(400);
    expect(overlayIn(frame)).not.toBeNull();
    await advance(BLUEPRINT_DRAW_MS);
    expect(stateOf(frame)).toBe('reveal');
    expect(measure).toHaveBeenCalledTimes(2);
  });

  describe('expected size', () => {
    it('waits for a window that is still being resized before measuring, so the blueprint is not cut off', async () => {
      requestReveal(true);
      install();
      setBlueprintExpectedSize({ width: 260, height: 120 });
      const frame = mountFrame();
      sizeFrame(frame, 300, 138);
      await advance(300);
      expect(measure).not.toHaveBeenCalled();
      expect(overlayIn(frame)).toBeNull();

      sizeFrame(frame, 260, 120);
      await advance(200);
      expect(measure).toHaveBeenCalled();
      expect(overlayIn(frame)).not.toBeNull();
    });

    it('measures at once when the window is already the expected size', async () => {
      requestReveal(true);
      install();
      setBlueprintExpectedSize({ width: 260, height: 120 });
      const frame = mountFrame();
      sizeFrame(frame, 260.5, 119.4);
      await advance(100);
      expect(overlayIn(frame)).not.toBeNull();
    });

    it('measures anyway when the window never reaches the expected size', async () => {
      requestReveal(true);
      install();
      setBlueprintExpectedSize({ width: 260, height: 120 });
      const frame = mountFrame();
      sizeFrame(frame, 300, 138);
      await advance(300);
      expect(overlayIn(frame)).toBeNull();
      await advance(400);
      expect(overlayIn(frame)).not.toBeNull();
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');
    });
  });

  describe('replay', () => {
    async function playOnce(frame: HTMLElement) {
      await advance(400);
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');
    }

    it('plays again each time the window comes back after going out of sight', async () => {
      requestReveal(true);
      install();
      const frame = mountFrame();
      await playOnce(frame);

      reportVisibility(false, true);
      expect(stateOf(frame)).toBe('hidden');
      await advance(2000);
      expect(overlayIn(frame)).toBeNull();
      expect(stateOf(frame)).toBe('hidden');

      reportVisibility(true, true);
      await advance(400);
      expect(overlayIn(frame)).not.toBeNull();
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');

      reportVisibility(false, true);
      reportVisibility(true, true);
      await advance(400);
      expect(overlayIn(frame)).not.toBeNull();
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');
    });

    it('replays on a window that opened with the effect off when the setting is on by the next appearance', async () => {
      requestReveal(false);
      install();
      const frame = mountFrame();
      await advance(400);
      expect(stateOf(frame)).toBeNull();

      reportVisibility(false, true);
      expect(stateOf(frame)).toBe('hidden');
      reportVisibility(true, true);
      await advance(400);
      expect(overlayIn(frame)).not.toBeNull();
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');
    });

    it('ignores a replay while one is already playing', async () => {
      requestReveal(true);
      install();
      const frame = mountFrame();
      await advance(400);
      const shapesBefore = frame.querySelectorAll('.basil-blueprint__shape').length;

      reportVisibility(true, true);
      expect(overlayIn(frame)).not.toBeNull();
      expect(frame.querySelectorAll('.basil-blueprint__shape')).toHaveLength(shapesBefore);
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(frame)).toBe('reveal');
    });

    it('does not hold the window while the setting is off, and shows a held one normally when it comes back with the setting off', async () => {
      requestReveal(true);
      install();
      const frame = mountFrame();
      await playOnce(frame);

      reportVisibility(false, false);
      expect(stateOf(frame)).toBe('reveal');

      reportVisibility(false, true);
      expect(stateOf(frame)).toBe('hidden');
      reportVisibility(true, false);
      expect(stateOf(frame)).toBeNull();
      expect(overlayIn(frame)).toBeNull();
    });

    it('does not hold or replay under reduced motion', async () => {
      requestReveal(false);
      install();
      const frame = mountFrame();
      stubReducedMotion(true);
      reportVisibility(false, true);
      expect(stateOf(frame)).toBeNull();
      reportVisibility(true, true);
      await advance(2000);
      expect(stateOf(frame)).toBeNull();
      expect(overlayIn(frame)).toBeNull();
    });

    it('ignores visibility reports before the window has a frame', async () => {
      requestReveal(true);
      install();
      reportVisibility(false, true);
      reportVisibility(true, true);
      const frame = mountFrame();
      await advance(400);
      expect(overlayIn(frame)).not.toBeNull();
    });
  });

  describe('fallbacks', () => {
    it('shows the window without a blueprint when nothing can be measured', async () => {
      requestReveal(true);
      measure.mockReturnValue(null);
      install();
      const frame = mountFrame();
      await advance(2500);

      expect(stateOf(frame)).toBe('reveal');
      expect(overlayIn(frame)).toBeNull();
    });

    it('shows the window when it never becomes ready', async () => {
      requestReveal(true);
      document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
      install();
      const frame = mountFrame();
      await advance(3200);

      expect(stateOf(frame)).toBe('reveal');
      expect(overlayIn(frame)).toBeNull();
      expect(measure).not.toHaveBeenCalled();
    });

    it('skips the whole reveal under reduced motion', async () => {
      stubReducedMotion(true);
      requestReveal(true);
      install();
      const frame = mountFrame();
      await advance(2000);

      expect(stateOf(frame)).toBeNull();
      expect(overlayIn(frame)).toBeNull();
      expect(measure).not.toHaveBeenCalled();
    });

    it('never touches an embedded pane, and ignores visibility reports for it', async () => {
      requestReveal(true);
      install();
      const frame = mountFrame('basil-webkit-window-frame--embedded');
      await advance(2000);
      expect(stateOf(frame)).toBeNull();

      reportVisibility(false, true);
      reportVisibility(true, true);
      await advance(2000);
      expect(stateOf(frame)).toBeNull();
      expect(overlayIn(frame)).toBeNull();
      expect(measure).not.toHaveBeenCalled();
    });

    it('keeps a replacement frame hidden and draws on it when React swaps the frame element', async () => {
      requestReveal(true);
      install();
      const placeholder = mountFrame('', false);
      await advance(100);
      expect(stateOf(placeholder)).toBe('hidden');
      expect(measure).not.toHaveBeenCalled();

      placeholder.remove();
      const real = mountFrame();
      await advance(0);
      expect(stateOf(real)).toBe('hidden');

      await advance(400);
      expect(overlayIn(real)).not.toBeNull();
      await advance(BLUEPRINT_DRAW_MS);
      expect(stateOf(real)).toBe('reveal');
    });

    it('plays once on a page and does not redraw when the content changes afterward', async () => {
      requestReveal(true);
      install();
      const frame = mountFrame();
      await advance(400);
      await advance(BLUEPRINT_DRAW_MS);
      measure.mockClear();

      frame.firstElementChild!.appendChild(document.createElement('span'));
      await advance(2000);
      expect(measure).not.toHaveBeenCalled();
      expect(stateOf(frame)).toBe('reveal');
    });
  });

  it('removes the blueprint once it reports that it has faded out', async () => {
    requestReveal(true);
    install();
    const frame = mountFrame();
    await advance(400);
    const svg = overlayIn(frame)!;
    const fade = (target: Element, animationName: string) => target.dispatchEvent(Object.assign(new Event('animationend'), { animationName }));

    fade(svg.firstElementChild!, 'basil-blueprint-fade');
    expect(overlayIn(frame)).not.toBeNull();
    fade(svg, 'basil-blueprint-draw');
    expect(overlayIn(frame)).not.toBeNull();
    fade(svg, 'basil-blueprint-fade');
    expect(overlayIn(frame)).toBeNull();
  });

  it('installs once per page', () => {
    requestReveal(false);
    const first = installBlueprintReveal();
    const second = installBlueprintReveal();
    uninstall = first;
    expect(second).toBe(first);
  });
});

describe('the outline that starts before the content is ready', () => {
  const OUTLINE = { width: 300, height: 140, frame: SAMPLE.frame };

  function startLoadingFrame() {
    requestReveal(true);
    measureOutlineOnly.mockReturnValue(OUTLINE);
    install();
    const frame = mountFrame();
    frame.setAttribute(BLUEPRINT_PENDING_ATTRIBUTE, 'true');
    return frame;
  }

  it('draws the outline at once while the content is still loading', async () => {
    const frame = startLoadingFrame();
    await advance(0);

    expect(stateOf(frame)).toBe('hidden');
    expect(overlayIn(frame)).not.toBeNull();
    expect(frame.querySelectorAll('.basil-blueprint__shape')).toHaveLength(1);
    expect(overlayIn(frame)!.classList.contains('basil-blueprint--pending')).toBe(true);
    expect(measure).not.toHaveBeenCalled();
  });

  it('keeps the outline on screen for as long as the content takes, without showing the window', async () => {
    const frame = startLoadingFrame();
    await advance(2000);

    expect(stateOf(frame)).toBe('hidden');
    expect(overlayIn(frame)!.classList.contains('basil-blueprint--pending')).toBe(true);
  });

  it('adds the layout to the same drawing when the content arrives, then reveals sooner than a cold draw', async () => {
    const frame = startLoadingFrame();
    await advance(500);
    const outline = overlayIn(frame)!;

    frame.removeAttribute(BLUEPRINT_PENDING_ATTRIBUTE);
    await advance(200);

    expect(overlayIn(frame)).toBe(outline);
    expect(outline.classList.contains('basil-blueprint--pending')).toBe(false);
    expect(frame.querySelectorAll('.basil-blueprint__shape')).toHaveLength(4);

    await advance(BLUEPRINT_WARM_DRAW_MS);
    expect(stateOf(frame)).toBe('reveal');
    expect(BLUEPRINT_WARM_DRAW_MS).toBeLessThan(BLUEPRINT_DRAW_MS);
  });

  it('does not treat its own strokes as page activity', async () => {
    const frame = startLoadingFrame();
    await advance(0);
    frame.removeAttribute(BLUEPRINT_PENDING_ATTRIBUTE);
    const before = measure.mock.calls.length;
    await advance(100);
    // Quiet for the settle time despite the overlay having just been added, so the measurement is taken.
    expect(measure.mock.calls.length).toBeGreaterThan(before);
  });

  it('fades the outline out and shows the window when the content never arrives', async () => {
    const frame = startLoadingFrame();
    await advance(3500);

    expect(stateOf(frame)).toBe('reveal');
    const svg = overlayIn(frame);
    expect(svg === null || !svg.classList.contains('basil-blueprint--pending')).toBe(true);
    expect(svg === null || svg.style.getPropertyValue('--bp-fade-delay') === '0s').toBe(true);
  });

  it('waits for a size the host is resizing to before starting the outline', async () => {
    requestReveal(true);
    measureOutlineOnly.mockReturnValue(OUTLINE);
    setBlueprintExpectedSize({ width: 300, height: 140 });
    install();
    const frame = mountFrame();
    sizeFrame(frame, 200, 100);
    frame.setAttribute(BLUEPRINT_PENDING_ATTRIBUTE, 'true');
    await advance(100);
    expect(overlayIn(frame)).toBeNull();

    sizeFrame(frame, 300, 140);
    frame.setAttribute('data-nudge', '1');
    document.body.appendChild(document.createElement('span'));
    await advance(300);
    expect(overlayIn(frame)).not.toBeNull();
  });

  it('starts no outline when there is no layout to measure', async () => {
    requestReveal(true);
    measureOutlineOnly.mockReturnValue(null);
    install();
    const frame = mountFrame();
    frame.setAttribute(BLUEPRINT_PENDING_ATTRIBUTE, 'true');
    await advance(500);
    expect(overlayIn(frame)).toBeNull();
  });
});

describe('blueprintRevealRequested', () => {
  it('is true only when the host set the flag to true', () => {
    expect(blueprintRevealRequested()).toBe(false);
    requestReveal(false);
    expect(blueprintRevealRequested()).toBe(false);
    requestReveal(true);
    expect(blueprintRevealRequested()).toBe(true);
  });
});
