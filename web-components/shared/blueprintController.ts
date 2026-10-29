import { HOST_THEME_APPLIED_EVENT, isHostThemeApplied } from './hostThemeSignal';
import { measureBlueprint, measureOutline, type Blueprint } from './blueprintMeasure';
import {
  BLUEPRINT_DRAW_MS,
  BLUEPRINT_PENDING_CLASS,
  BLUEPRINT_WARM_DRAW_MS,
  completeBlueprintOverlay,
  createBlueprintOutlineOverlay,
  createBlueprintOverlay,
  fadeOutBlueprintOverlay,
} from './blueprintOverlay';
import './blueprint-reveal.css';

/** Set on the window's frame element: `hidden` while the blueprint is measured and drawn, `reveal` as everything fades in. blueprint-reveal.css keys off it. React never owns this attribute, so a re-render cannot clear it. */
export const BLUEPRINT_FRAME_ATTRIBUTE = 'data-basil-blueprint';
/** A surface whose frame, or something inside it, carries this attribute is not showing its real state yet (a loading shell, say), so nothing is measured until it is gone. */
export const BLUEPRINT_PENDING_ATTRIBUTE = 'data-blueprint-pending';
/** The window event the native side dispatches into every page when a window goes out of sight or comes back. The detail is `{ visible: boolean; blueprintReveal: boolean }`, where the second field is the live setting. */
export const WINDOW_VISIBILITY_EVENT = 'basil-window-visibility';

const FRAME_SELECTOR = '.basil-webkit-window-frame';
const EMBEDDED_FRAME_CLASS = 'basil-webkit-window-frame--embedded';
const SURFACE_SELECTOR = '.basil-webkit-window-surface';

/** How long the frame must go without a change to its content or size before it is measured, and the longest that wait may take. The window is invisible the whole time, so the settle is kept short. */
const SETTLE_MS = 60;
const QUIET_MAX_MS = 400;
/** How long the surface is given to become ready (theme applied, no pending marker) before it is simply shown, and how often readiness is re-checked when nothing wakes the wait. */
const READY_MAX_MS = 3000;
const READY_POLL_MS = 250;
/** How often the surface is measured until it has a layout, and the longest that takes before the content is shown without a blueprint. */
const PROBE_POLL_MS = 40;
const PROBE_MAX_MS = 1500;
const FONTS_MAX_MS = 150;
/** How often, and for how long at most, the frame's size is compared with the size its host is resizing the window to before the blueprint is measured anyway. */
const SIZE_POLL_MS = 30;
const SIZE_WAIT_MAX_MS = 400;
/** How far the frame's size may be from the expected size, in pixels, and still count as having arrived. */
const SIZE_TOLERANCE_PX = 1.5;
/** How long after the content has faded in a lingering drawing is removed, if its own fade-out never reported. */
const OVERLAY_LINGER_MS = 1000;

type BlueprintPhase = 'off' | 'waiting' | 'armed' | 'measuring' | 'drawing' | 'done';

export interface BlueprintRevealInstallOptions {
  /** A CSS selector for loading shells that paint boxes of their own, matched against the frame and everything inside it. Nothing is measured while it matches. The pending attribute is always honored in addition. */
  notReadySelector?: string;
}

interface ExpectedSize {
  width: number;
  height: number;
}

interface WindowVisibilityDetail {
  visible?: boolean;
  blueprintReveal?: boolean;
}

let expectedSize: ExpectedSize | null = null;
let installed: (() => void) | null = null;

/** A window that opens at one size and is then resized by its host would be measured at the wrong size, and the blueprint cut off at its right and bottom edges. A surface that knows the size its host is about to resize to registers it here, and the measurement waits for the frame to reach it. Pass null once the size is no longer pending. */
export function setBlueprintExpectedSize(size: ExpectedSize | null): void {
  expectedSize = size;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** True when the host asked for the blueprint reveal. The native side sets this flag before the page's scripts run, so the content can be hidden from its very first paint instead of appearing and then being drawn over. */
export function blueprintRevealRequested(): boolean {
  return typeof window !== 'undefined' && (window as Window & { basilBlueprintReveal?: boolean }).basilBlueprintReveal === true;
}

/** The window's own frame: the first one that is not an embedded pane without window chrome. */
function findFrame(): HTMLElement | null {
  for (const candidate of Array.from(document.querySelectorAll<HTMLElement>(FRAME_SELECTOR))) {
    if (!candidate.classList.contains(EMBEDDED_FRAME_CLASS)) return candidate;
  }
  return null;
}

/**
 * Installs the blueprint reveal for this page. When the surface first appears, and again each time the host reports the window coming back into sight, the window's content and chrome are hidden, a green blueprint of its outline and layout is drawn, and everything fades in. One call per entry point is all a surface needs: the frame and its surface are found by their existing window-chrome classes.
 * Reduced motion, a failed measurement, and a surface that never becomes ready all end with the content shown. Embedded panes (frames marked embedded) are never touched. Returns a function that removes the installation, which tests use.
 */
export function installBlueprintReveal(options: BlueprintRevealInstallOptions = {}): () => void {
  if (installed) return installed;

  const notReadySelector = options.notReadySelector ? `[${BLUEPRINT_PENDING_ATTRIBUTE}], ${options.notReadySelector}` : `[${BLUEPRINT_PENDING_ATTRIBUTE}]`;
  let phase: BlueprintPhase = blueprintRevealRequested() && !prefersReducedMotion() ? 'waiting' : 'off';
  let frame: HTMLElement | null = null;
  let overlay: SVGSVGElement | null = null;
  let runId = 0;
  let lastActivity = Date.now();
  let wake: (() => void) | null = null;
  const timers = new Set<number>();
  const ownOverlays = new WeakSet<Node>();

  const hiding = () => phase === 'armed' || phase === 'measuring' || phase === 'drawing';

  const pause = (ms: number, interruptible: boolean) =>
    new Promise<void>((resolve) => {
      const done = () => {
        window.clearTimeout(timer);
        timers.delete(timer);
        if (wake === done) wake = null;
        resolve();
      };
      const timer = window.setTimeout(done, ms);
      timers.add(timer);
      if (interruptible) wake = done;
    });

  const noteActivity = () => {
    lastActivity = Date.now();
    wake?.();
  };

  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(noteActivity) : null;

  const removeOverlay = () => {
    overlay?.remove();
    overlay = null;
  };

  /** Finds the current frame, keeping it hidden while the blueprint is playing: React may replace the frame element (a loading placeholder giving way to the real window, say), and the replacement must not flash. */
  const resolveFrame = (): HTMLElement | null => {
    const found = findFrame();
    if (found !== frame) {
      frame = found;
      resizeObserver?.disconnect();
      if (frame) resizeObserver?.observe(frame);
      if (overlay && !frame?.contains(overlay)) removeOverlay();
    }
    if (frame && hiding() && frame.getAttribute(BLUEPRINT_FRAME_ATTRIBUTE) !== 'hidden') frame.setAttribute(BLUEPRINT_FRAME_ATTRIBUTE, 'hidden');
    return frame;
  };

  const isOwnRecord = (record: MutationRecord) =>
    (overlay !== null && overlay.contains(record.target)) ||
    (record.type === 'childList' && [...Array.from(record.addedNodes), ...Array.from(record.removedNodes)].every((node) => ownOverlays.has(node)));

  const observer = new MutationObserver((records) => {
    if (!records.some((record) => !isOwnRecord(record))) return;
    if (phase === 'waiting') {
      const found = findFrame();
      if (found) beginPlaying();
    } else if (hiding()) {
      resolveFrame();
    }
    noteActivity();
  });
  const observe = () => observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: [BLUEPRINT_PENDING_ATTRIBUTE] });

  const onThemeApplied = () => noteActivity();

  const finish = () => {
    phase = 'done';
    observer.disconnect();
    resizeObserver?.disconnect();
    const target = resolveFrame();
    target?.setAttribute(BLUEPRINT_FRAME_ATTRIBUTE, 'reveal');
    if (overlay) {
      // An outline still waiting for a layout that never came leaves with the window's content arriving, instead of freezing on screen.
      if (overlay.classList.contains(BLUEPRINT_PENDING_CLASS)) fadeOutBlueprintOverlay(overlay);
      const lingering = overlay;
      timers.add(window.setTimeout(() => lingering.remove(), OVERLAY_LINGER_MS));
    }
  };

  const isPending = (target: HTMLElement) => target.matches(notReadySelector) || target.querySelector(notReadySelector) !== null;
  const isReady = () => {
    const target = resolveFrame();
    return target !== null && isHostThemeApplied() && !isPending(target);
  };

  const read = (): Blueprint | null => {
    const target = resolveFrame();
    const surface = target?.querySelector<HTMLElement>(SURFACE_SELECTOR);
    return target && surface ? measureBlueprint(target, surface) : null;
  };

  const sizeArrived = () => {
    const target = frame;
    if (!target || !expectedSize) return true;
    return Math.abs(target.offsetWidth - expectedSize.width) <= SIZE_TOLERANCE_PX && Math.abs(target.offsetHeight - expectedSize.height) <= SIZE_TOLERANCE_PX;
  };

  /** Begins the drawing with just the window's outline, as soon as the window has a size to draw it at. This is what makes a surface with an inherent load time answer the moment it is invoked: the outline traces while the content is still loading, and the layout is added to it later. Nothing is started while a size the host is about to resize to has not arrived, or while there is no layout. */
  const startOutline = () => {
    if (overlay || phase !== 'measuring') return;
    const target = resolveFrame();
    const surface = target?.querySelector<HTMLElement>(SURFACE_SELECTOR);
    if (!target || !surface || !sizeArrived()) return;
    const outline = measureOutline(target, surface);
    if (!outline) return;
    overlay = createBlueprintOutlineOverlay(outline, removeOverlay);
    ownOverlays.add(overlay);
    target.appendChild(overlay);
  };

  const draw = (blueprint: Blueprint) => {
    const target = resolveFrame();
    if (!target) {
      finish();
      return;
    }
    let drawMs = BLUEPRINT_DRAW_MS;
    if (overlay && target.contains(overlay) && overlay.classList.contains(BLUEPRINT_PENDING_CLASS)) {
      completeBlueprintOverlay(overlay, blueprint, true);
      drawMs = BLUEPRINT_WARM_DRAW_MS;
    } else {
      removeOverlay();
      overlay = createBlueprintOverlay(blueprint, removeOverlay);
      ownOverlays.add(overlay);
      target.appendChild(overlay);
    }
    phase = 'drawing';
    const thisRun = runId;
    timers.add(
      window.setTimeout(() => {
        if (thisRun === runId) finish();
      }, drawMs),
    );
  };

  /** Waits for the surface to be ready and still, measures it, and starts the drawing. Any step that cannot complete in time ends with the content shown instead. */
  const run = async () => {
    const id = ++runId;
    const stale = () => id !== runId;
    const started = Date.now();
    lastActivity = started;

    startOutline();
    while (!isReady()) {
      if (Date.now() - started >= READY_MAX_MS) {
        finish();
        return;
      }
      await pause(READY_POLL_MS, true);
      if (stale()) return;
      startOutline();
    }

    const quietStarted = Date.now();
    for (;;) {
      const quietFor = Date.now() - lastActivity;
      if (quietFor >= SETTLE_MS || Date.now() - quietStarted >= QUIET_MAX_MS) break;
      await pause(SETTLE_MS - quietFor, false);
      if (stale()) return;
    }

    for (let waited = 0; waited < SIZE_WAIT_MAX_MS && !sizeArrived(); waited += SIZE_POLL_MS) {
      await pause(SIZE_POLL_MS, false);
      if (stale()) return;
    }

    let measured: Blueprint | null = null;
    for (let waited = 0; waited < PROBE_MAX_MS; waited += PROBE_POLL_MS) {
      if (isReady()) measured = read();
      if (measured) break;
      await pause(PROBE_POLL_MS, false);
      if (stale()) return;
    }
    if (!measured) {
      finish();
      return;
    }

    await Promise.race([document.fonts?.ready ?? Promise.resolve(), pause(FONTS_MAX_MS, false)]);
    if (stale()) return;
    draw(read() ?? measured);
  };

  const beginPlaying = () => {
    removeOverlay();
    phase = 'measuring';
    resolveFrame();
    observe();
    void run();
  };

  const onWindowVisibility = (event: Event) => {
    const detail = ((event as CustomEvent<WindowVisibilityDetail>).detail ?? {}) as WindowVisibilityDetail;
    const enabled = detail.blueprintReveal === true && !prefersReducedMotion();

    if (detail.visible === false) {
      // Out of sight: hold the window hidden so the next appearance can replay without a flash of the old content.
      if (!enabled || (phase !== 'done' && phase !== 'off') || !findFrame()) return;
      runId += 1;
      removeOverlay();
      phase = 'armed';
      resolveFrame();
      observe();
      return;
    }

    if (phase === 'measuring' || phase === 'drawing' || phase === 'waiting') return;
    if (!enabled) {
      if (phase === 'armed') {
        phase = 'off';
        observer.disconnect();
        resolveFrame()?.removeAttribute(BLUEPRINT_FRAME_ATTRIBUTE);
      }
      return;
    }
    if (findFrame()) beginPlaying();
  };

  window.addEventListener(WINDOW_VISIBILITY_EVENT, onWindowVisibility);
  window.addEventListener(HOST_THEME_APPLIED_EVENT, onThemeApplied);
  if (phase === 'waiting') {
    observe();
    if (findFrame()) beginPlaying();
  }

  installed = () => {
    window.removeEventListener(WINDOW_VISIBILITY_EVENT, onWindowVisibility);
    window.removeEventListener(HOST_THEME_APPLIED_EVENT, onThemeApplied);
    observer.disconnect();
    resizeObserver?.disconnect();
    runId += 1;
    timers.forEach((timer) => window.clearTimeout(timer));
    timers.clear();
    removeOverlay();
    installed = null;
  };
  return installed;
}
