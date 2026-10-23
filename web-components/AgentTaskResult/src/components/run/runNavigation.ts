import type { AgentRunOverviewStage } from './agentRunPresentation';

export type RunNavigationSection = 'activity' | 'result';

export type RunNavigationTarget =
  | { kind: 'run' }
  | { kind: 'latest' }
  | { kind: 'interaction'; entryId: string }
  | { kind: 'section'; section: RunNavigationSection };

export interface RunNavigationRequest {
  nonce: number;
  runId: string;
  target: RunNavigationTarget;
}

// A turn becomes the location once its label reaches this fraction of the viewport height.
export const RUN_LOCATION_THRESHOLD_RATIO = 0.35;
const NAVIGATION_TOP_OFFSET_PX = 8;

export function navigationTargetForStage(stage: AgentRunOverviewStage): RunNavigationTarget {
  if (stage.kind === 'interaction' && stage.interaction) {
    return { kind: 'interaction', entryId: stage.interaction.entryId };
  }
  if (stage.kind === 'outcome') return { kind: 'section', section: 'result' };
  return { kind: 'section', section: 'activity' };
}

function attributeSelectorValue(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(value);
  return value.replace(/["\\]/g, '\\$&');
}

export function findRunNavigationElement(
  container: HTMLElement,
  request: Pick<RunNavigationRequest, 'runId' | 'target'>,
  isPriorRun: boolean,
): HTMLElement | null {
  const runId = attributeSelectorValue(request.runId);
  const runAnchor = container.querySelector<HTMLElement>(`[data-run-anchor="${runId}"]`);
  const scope: ParentNode | null = isPriorRun
    ? container.querySelector(`[data-run-content="${runId}"]`)
    : container;
  const findInRun = (selector: string): HTMLElement | null => {
    if (!scope) return null;
    return Array.from(scope.querySelectorAll<HTMLElement>(selector))
      .find(element => isPriorRun || !element.closest('[data-run-content]')) ?? null;
  };
  const { target } = request;
  const targetElement = target.kind === 'interaction'
    ? findInRun(`[data-interaction-entry-id="${attributeSelectorValue(target.entryId)}"]`)
    : target.kind === 'section'
      ? findInRun(`[data-run-section="${target.section}"]`)
      : null;
  return targetElement ?? runAnchor;
}

export function computeLocationRunId(container: HTMLElement, fallbackRunId: string): string {
  const anchors = Array.from(container.querySelectorAll<HTMLElement>('[data-run-anchor]'));
  if (anchors.length === 0) return fallbackRunId;
  const threshold = container.getBoundingClientRect().top + container.clientHeight * RUN_LOCATION_THRESHOLD_RATIO;
  let locationRunId = anchors[0].dataset.runAnchor || fallbackRunId;
  for (const anchor of anchors) {
    if (anchor.getBoundingClientRect().top > threshold) break;
    locationRunId = anchor.dataset.runAnchor || locationRunId;
  }
  return locationRunId;
}

// Collapsed earlier turns are short, so at the very top several labels can sit above the threshold at once; the top edge must still mean the first turn.
export function resolveScrollLocationRunId(container: HTMLElement, currentRunId: string, atBottom: boolean): string {
  const firstAnchor = container.querySelector<HTMLElement>('[data-run-anchor]');
  if (!firstAnchor) return currentRunId;
  const isScrollable = container.scrollHeight > container.clientHeight;
  if (isScrollable && container.scrollTop <= 1) return firstAnchor.dataset.runAnchor || currentRunId;
  if (atBottom) return currentRunId;
  return computeLocationRunId(container, currentRunId);
}

export function scrollOffsetForElement(container: HTMLElement, element: HTMLElement): number {
  const offset = element.getBoundingClientRect().top - container.getBoundingClientRect().top;
  return Math.max(0, container.scrollTop + offset - NAVIGATION_TOP_OFFSET_PX);
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function flashNavigationTarget(element: HTMLElement): void {
  element.removeAttribute('data-navigation-flash');
  // Reading layout restarts the animation when the same element is navigated to twice in a row.
  void element.offsetWidth;
  element.setAttribute('data-navigation-flash', '');
  const handleAnimationEnd = (event: AnimationEvent) => {
    if (event.target !== element) return;
    element.removeAttribute('data-navigation-flash');
    element.removeEventListener('animationend', handleAnimationEnd);
  };
  element.addEventListener('animationend', handleAnimationEnd);
}
