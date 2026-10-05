import './basil-tooltip.css';
import { computeTooltipPosition, type TooltipAnchorBox, type TooltipPlacement } from './tooltipPosition';

export const TOOLTIP_SHOW_DELAY_MS = 500;
export const TOOLTIP_ELEMENT_ID = 'basil-tooltip';

const TOOLTIP_TARGET_SELECTOR = '[data-tooltip], [title]';
const EXCLUDED_TARGET_TAGS = new Set(['IFRAME', 'HTML', 'BODY']);
const TRUNCATION_DESCENDANT_LIMIT = 24;
// Centering on a full-width row or a tall block puts the tooltip far from the pointer, so larger targets anchor to the pointer instead.
const POINTER_ANCHOR_MIN_WIDTH_PX = 160;
const POINTER_ANCHOR_MIN_HEIGHT_PX = 48;
const POINTER_CURSOR_HEIGHT_PX = 18;
const PLACEMENTS: readonly TooltipPlacement[] = ['above', 'below', 'left', 'right'];

type TooltipSource = 'pointer' | 'focus';

interface ActiveTooltipTarget {
  element: Element;
  source: TooltipSource;
  suppressed: boolean;
}

interface StashedTitle {
  element: Element;
  title: string;
  addedLabel: boolean;
}

interface DescribedTarget {
  element: Element;
  previousDescribedBy: string | null;
}

const installations = new WeakMap<Document, () => void>();

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function toNode(target: EventTarget | null): Node | null {
  return target && typeof (target as Partial<Node>).nodeType === 'number' ? (target as Node) : null;
}

function toElement(target: EventTarget | null): Element | null {
  const node = toNode(target);
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
}

function isEligibleTarget(element: Element): boolean {
  return !EXCLUDED_TARGET_TAGS.has(element.tagName.toUpperCase()) && !element.closest('.basil-tooltip');
}

function resolveTooltipTarget(start: Element | null): Element | null {
  const candidate = start?.closest(TOOLTIP_TARGET_SELECTOR) ?? null;
  return candidate && isEligibleTarget(candidate) ? candidate : null;
}

function clipsOverflow(element: Element): boolean {
  const view = element.ownerDocument.defaultView;
  if (!view) return false;
  const style = view.getComputedStyle(element);
  const clipsContent = [style.overflowX, style.overflowY, style.overflow].some((value) => Boolean(value) && value !== 'visible');
  return clipsContent && (element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1);
}

function isTruncated(element: Element): boolean {
  if (clipsOverflow(element)) return true;
  const descendants = element.getElementsByTagName('*');
  const limit = Math.min(descendants.length, TRUNCATION_DESCENDANT_LIMIT);
  for (let index = 0; index < limit; index += 1) {
    if (clipsOverflow(descendants[index])) return true;
  }
  return false;
}

function tooltipTextFor(element: Element, title: string | null): string | null {
  const explicit = element.getAttribute('data-tooltip');
  if (explicit !== null) {
    const text = explicit.trim();
    if (!text) return null;
    if (element.getAttribute('data-tooltip-when') === 'truncated' && !isTruncated(element)) return null;
    return text;
  }
  const text = title?.trim() ?? '';
  if (!text) return null;
  if (normalizeText(text) === normalizeText(element.textContent ?? '') && !isTruncated(element)) return null;
  return text;
}

function parsePlacement(value: string | null): TooltipPlacement {
  return PLACEMENTS.find((placement) => placement === value) ?? 'below';
}

function reactTitleProp(element: Element): string | null | undefined {
  const propsKey = Object.keys(element).find((key) => key.startsWith('__reactProps$'));
  if (!propsKey) return undefined;
  const props = (element as unknown as Record<string, unknown>)[propsKey];
  if (!props || typeof props !== 'object') return undefined;
  const title = (props as { title?: unknown }).title;
  return title === undefined || title === null || title === false ? null : String(title);
}

function matchesFocusVisible(element: Element): boolean {
  try {
    return element.matches(':focus-visible');
  } catch {
    return element.matches(':focus');
  }
}

export function installBasilTooltips(doc: Document = document): () => void {
  const existing = installations.get(doc);
  if (existing) return existing;
  const view = doc.defaultView;

  let active: ActiveTooltipTarget | null = null;
  let stashed: StashedTitle[] = [];
  let titleObserver: MutationObserver | null = null;
  let described: DescribedTarget | null = null;
  let showTimer: ReturnType<typeof setTimeout> | undefined;
  let tooltip: HTMLElement | null = null;
  let pointer: { x: number; y: number } | null = null;

  function tooltipElement(): HTMLElement {
    if (tooltip?.isConnected) return tooltip;
    const element = doc.createElement('div');
    element.id = TOOLTIP_ELEMENT_ID;
    element.className = 'basil-tooltip';
    element.setAttribute('role', 'tooltip');
    doc.body.appendChild(element);
    tooltip = element;
    return element;
  }

  function currentTitle(element: Element): string | null {
    const entry = stashed.find((candidate) => candidate.element === element);
    return entry ? entry.title : element.getAttribute('title');
  }

  function clearShowTimer(): void {
    if (showTimer === undefined) return;
    clearTimeout(showTimer);
    showTimer = undefined;
  }

  function describeTarget(element: Element): void {
    if (described?.element === element) return;
    undescribeTarget();
    const previousDescribedBy = element.getAttribute('aria-describedby');
    const ids = new Set((previousDescribedBy ?? '').split(/\s+/).filter(Boolean));
    ids.add(TOOLTIP_ELEMENT_ID);
    element.setAttribute('aria-describedby', Array.from(ids).join(' '));
    described = { element, previousDescribedBy };
  }

  function undescribeTarget(): void {
    if (!described) return;
    const { element, previousDescribedBy } = described;
    described = null;
    if (previousDescribedBy === null) element.removeAttribute('aria-describedby');
    else element.setAttribute('aria-describedby', previousDescribedBy);
  }

  function hideTooltip(): void {
    tooltip?.classList.remove('is-visible');
    undescribeTarget();
  }

  function tooltipAnchor(target: Element): TooltipAnchorBox {
    const rect = target.getBoundingClientRect();
    const isLarge = rect.width > POINTER_ANCHOR_MIN_WIDTH_PX || rect.height > POINTER_ANCHOR_MIN_HEIGHT_PX;
    if (active?.source !== 'pointer' || !pointer || !isLarge) {
      return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
    }
    if (rect.height <= POINTER_ANCHOR_MIN_HEIGHT_PX) {
      return { top: rect.top, left: pointer.x, width: 0, height: rect.height };
    }
    return { top: pointer.y, left: pointer.x, width: 0, height: POINTER_CURSOR_HEIGHT_PX };
  }

  function renderTooltip(target: Element, text: string): void {
    const element = tooltipElement();
    element.textContent = text;
    const position = computeTooltipPosition(
      tooltipAnchor(target),
      { width: element.offsetWidth, height: element.offsetHeight },
      { width: view?.innerWidth ?? doc.documentElement.clientWidth, height: view?.innerHeight ?? doc.documentElement.clientHeight },
      parsePlacement(target.getAttribute('data-tooltip-placement')),
    );
    element.style.top = `${position.top}px`;
    element.style.left = `${position.left}px`;
    element.dataset.placement = position.placement;
    void element.offsetHeight;
    element.classList.add('is-visible');
    describeTarget(target);
  }

  function updateTooltip(): void {
    if (!active || active.suppressed) return;
    const text = tooltipTextFor(active.element, currentTitle(active.element));
    if (text) renderTooltip(active.element, text);
    else hideTooltip();
  }

  function showTooltip(): void {
    showTimer = undefined;
    if (active && !active.element.isConnected) {
      endTooltip();
      return;
    }
    updateTooltip();
  }

  function stashTitles(target: Element): void {
    for (let element: Element | null = target; element && element !== doc.body; element = element.parentElement) {
      const title = element.getAttribute('title');
      if (title === null) continue;
      const addedLabel = element === target
        && !element.hasAttribute('aria-label')
        && !element.hasAttribute('aria-labelledby')
        && normalizeText(element.textContent ?? '') === '';
      element.removeAttribute('title');
      if (addedLabel) element.setAttribute('aria-label', title);
      stashed.push({ element, title, addedLabel });
    }
    if (typeof MutationObserver === 'undefined') return;
    titleObserver = new MutationObserver(() => {
      const replacement = target.getAttribute('title');
      if (replacement === null) return;
      target.removeAttribute('title');
      const entry = stashed.find((candidate) => candidate.element === target);
      if (entry) {
        if (entry.addedLabel) target.setAttribute('aria-label', replacement);
        entry.title = replacement;
      } else {
        stashed.unshift({ element: target, title: replacement, addedLabel: false });
      }
      if (tooltip?.classList.contains('is-visible')) updateTooltip();
    });
    titleObserver.observe(target, { attributes: true, attributeFilter: ['title'] });
  }

  function restoreTitles(): void {
    titleObserver?.disconnect();
    titleObserver = null;
    for (const { element, title, addedLabel } of stashed) {
      if (addedLabel && element.getAttribute('aria-label') === title) element.removeAttribute('aria-label');
      const reactTitle = reactTitleProp(element);
      const restored = reactTitle === undefined ? title : reactTitle;
      if (restored && element.getAttribute('title') === null) element.setAttribute('title', restored);
    }
    stashed = [];
  }

  function endTooltip(): void {
    clearShowTimer();
    hideTooltip();
    restoreTitles();
    active = null;
  }

  function suppressTooltip(): void {
    if (!active) return;
    if (active.source === 'focus') {
      endTooltip();
      return;
    }
    clearShowTimer();
    hideTooltip();
    active.suppressed = true;
  }

  function beginTooltip(element: Element, source: TooltipSource): void {
    endTooltip();
    active = { element, source, suppressed: false };
    if (source === 'pointer') stashTitles(element);
    showTimer = setTimeout(showTooltip, TOOLTIP_SHOW_DELAY_MS);
  }

  function trackPointer(event: MouseEvent): void {
    pointer = { x: event.clientX, y: event.clientY };
  }

  function handleMouseOver(event: MouseEvent): void {
    trackPointer(event);
    if (active && !active.element.isConnected) endTooltip();
    const start = toElement(event.target);
    if (!start) return;
    if (active?.source === 'pointer' && active.element.contains(start)) {
      const inner = resolveTooltipTarget(start);
      if (inner && inner !== active.element && active.element.contains(inner)) beginTooltip(inner, 'pointer');
      return;
    }
    const target = resolveTooltipTarget(start);
    if (!target) return;
    if (active && target === active.element) {
      active.source = 'pointer';
      stashTitles(target);
      return;
    }
    beginTooltip(target, 'pointer');
  }

  function handleMouseOut(event: MouseEvent): void {
    if (!active || active.source !== 'pointer') return;
    const related = toNode(event.relatedTarget);
    if (related && active.element.contains(related)) return;
    endTooltip();
  }

  function handleFocusIn(event: FocusEvent): void {
    const element = toElement(event.target);
    if (!element || element === active?.element) return;
    if (!element.matches(TOOLTIP_TARGET_SELECTOR) || !isEligibleTarget(element) || !matchesFocusVisible(element)) return;
    beginTooltip(element, 'focus');
  }

  function handleFocusOut(): void {
    if (active?.source === 'focus') endTooltip();
  }

  function handleScroll(event: Event): void {
    if (!active) return;
    const scrolled = toNode(event.target);
    if (!scrolled || scrolled.contains(active.element)) suppressTooltip();
  }

  function handleViewportChange(): void {
    endTooltip();
  }

  function handleVisibilityChange(): void {
    if (doc.visibilityState === 'hidden') endTooltip();
  }

  doc.addEventListener('mouseover', handleMouseOver, true);
  doc.addEventListener('mouseout', handleMouseOut, true);
  doc.addEventListener('mousemove', trackPointer, { capture: true, passive: true });
  doc.addEventListener('mousedown', suppressTooltip, true);
  doc.addEventListener('keydown', suppressTooltip, true);
  doc.addEventListener('focusin', handleFocusIn, true);
  doc.addEventListener('focusout', handleFocusOut, true);
  doc.addEventListener('scroll', handleScroll, { capture: true, passive: true });
  doc.addEventListener('visibilitychange', handleVisibilityChange);
  view?.addEventListener('resize', handleViewportChange);
  view?.addEventListener('blur', handleViewportChange);

  function dispose(): void {
    endTooltip();
    doc.removeEventListener('mouseover', handleMouseOver, true);
    doc.removeEventListener('mouseout', handleMouseOut, true);
    doc.removeEventListener('mousemove', trackPointer, true);
    doc.removeEventListener('mousedown', suppressTooltip, true);
    doc.removeEventListener('keydown', suppressTooltip, true);
    doc.removeEventListener('focusin', handleFocusIn, true);
    doc.removeEventListener('focusout', handleFocusOut, true);
    doc.removeEventListener('scroll', handleScroll, true);
    doc.removeEventListener('visibilitychange', handleVisibilityChange);
    view?.removeEventListener('resize', handleViewportChange);
    view?.removeEventListener('blur', handleViewportChange);
    tooltip?.remove();
    tooltip = null;
    if (installations.get(doc) === dispose) installations.delete(doc);
  }

  installations.set(doc, dispose);
  return dispose;
}
