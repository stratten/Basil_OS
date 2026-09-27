export type SurfaceFinish = 'flat' | 'metal';

const STYLE_ELEMENT_ID = 'basil-surface-finish-style';
const SURFACE_TARGET_ATTRIBUTE = 'data-basil-surface-finish-target';
const SURFACE_OVERLAY_CLASS = 'basil-surface-finish-overlay';
let surfaceTargetObserver: MutationObserver | undefined;

const METAL_OVERLAY_CSS = `
html[data-surface-finish="metal"] [data-basil-surface-finish-target] {
  --basil-surface-finish-bands:
    linear-gradient(112deg, color-mix(in srgb, var(--background-primary) 70%, var(--primary)) 0%, transparent 23%, color-mix(in srgb, var(--background-primary) 82%, var(--primary)) 47%, transparent 70%, color-mix(in srgb, var(--background-primary) 74%, var(--primary)) 100%),
    linear-gradient(170deg, color-mix(in srgb, var(--background-primary) 88%, var(--primary)) 0%, transparent 36%, color-mix(in srgb, var(--background-primary) 93%, var(--primary)) 100%);
  position: relative;
  isolation: isolate;
}

html[data-surface-finish="metal"] .basil-surface-finish-overlay {
  position: absolute;
  inset: 0;
  z-index: 2147483646;
  border-radius: inherit;
  pointer-events: none;
  opacity: 0.34;
  background-image: var(--basil-surface-finish-bands);
  background-size: 100% 100%, 100% 100%;
  background-repeat: no-repeat;
}

html[data-surface-finish="metal"] .basil-webkit-window-frame > .basil-surface-finish-overlay {
  inset: calc(var(--basil-webkit-window-frame-inset) + 0.5px);
  border-radius: calc(var(--basil-webkit-window-corner-radius) - 0.5px);
}
`;

function ensureStyleInjected(): void {
  if (typeof document === 'undefined') return;
  if (document.getElementById(STYLE_ELEMENT_ID)) return;

  const style = document.createElement('style');
  style.id = STYLE_ELEMENT_ID;
  style.textContent = METAL_OVERLAY_CSS;
  document.head.appendChild(style);
}

function applySurfaceFinishTargets(): void {
  const existingTargets = document.querySelectorAll<HTMLElement>(`[${SURFACE_TARGET_ATTRIBUTE}]`);
  existingTargets.forEach((target) => target.removeAttribute(SURFACE_TARGET_ATTRIBUTE));
  document.querySelectorAll(`.${SURFACE_OVERLAY_CLASS}`).forEach((overlay) => overlay.remove());

  const windowFrames = document.querySelectorAll<HTMLElement>('.basil-webkit-window-frame');
  if (windowFrames.length > 0) {
    windowFrames.forEach(applySurfaceFinishTarget);
    return;
  }

  const roundedWindowSurfaces = document.querySelectorAll<HTMLElement>('.basil-webkit-window-surface');
  if (roundedWindowSurfaces.length > 0) {
    roundedWindowSurfaces.forEach(applySurfaceFinishTarget);
    return;
  }

  const root = document.getElementById('root');
  if (root) applySurfaceFinishTarget(root);
}

function applySurfaceFinishTarget(target: HTMLElement): void {
  target.setAttribute(SURFACE_TARGET_ATTRIBUTE, '');
  const overlay = document.createElement('div');
  overlay.className = SURFACE_OVERLAY_CLASS;
  overlay.setAttribute('aria-hidden', 'true');
  target.appendChild(overlay);
}

function observeForRoundedWindowSurface(): void {
  surfaceTargetObserver?.disconnect();
  if (document.querySelector('.basil-webkit-window-frame, .basil-webkit-window-surface')) return;

  surfaceTargetObserver = new MutationObserver(() => {
    if (!document.querySelector('.basil-webkit-window-frame, .basil-webkit-window-surface')) return;
    applySurfaceFinishTargets();
    surfaceTargetObserver?.disconnect();
    surfaceTargetObserver = undefined;
  });
  surfaceTargetObserver.observe(document.body, { childList: true, subtree: true });
}

export function applySurfaceFinish(finish?: string): void {
  if (typeof document === 'undefined') return;

  ensureStyleInjected();
  const surfaceFinish = finish === 'metal' ? 'metal' : 'flat';
  document.documentElement.dataset.surfaceFinish = surfaceFinish;
  if (surfaceFinish === 'flat') {
    surfaceTargetObserver?.disconnect();
    surfaceTargetObserver = undefined;
    document.querySelectorAll<HTMLElement>(`[${SURFACE_TARGET_ATTRIBUTE}]`).forEach((target) => {
      target.removeAttribute(SURFACE_TARGET_ATTRIBUTE);
    });
    document.querySelectorAll(`.${SURFACE_OVERLAY_CLASS}`).forEach((overlay) => overlay.remove());
    return;
  }

  applySurfaceFinishTargets();
  observeForRoundedWindowSurface();
}
