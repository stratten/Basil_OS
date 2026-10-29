import { blueprintRectLength, type Blueprint, type BlueprintOutline } from './blueprintMeasure';

/** Fraction of the website's blueprint pacing used here. The website draws for about 1.5 s; a hotkey widget cannot stay hidden that long, so every delay and duration is scaled to about half. blueprint-reveal.css carries the matching durations. */
export const BLUEPRINT_PACE = 0.55;
/** From the first stroke until the content starts to fade in over the blueprint, in milliseconds, when the whole blueprint is drawn in one go. The website's 1500 ms scaled by BLUEPRINT_PACE. */
export const BLUEPRINT_DRAW_MS = 820;
/** The lead the outline gets over the parts inside it, as a fraction of the pace: parts start drawing a tenth of the way down, after the outline has begun. */
const PARTS_LEAD = 0.1;
/** From completing a blueprint whose outline is already on screen until the content starts to fade in. The outline has had its head start, so the parts begin at once instead of after the lead. */
export const BLUEPRINT_WARM_DRAW_MS = Math.round(BLUEPRINT_DRAW_MS - PARTS_LEAD * BLUEPRINT_PACE * 1000);

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const STROKE_WIDTH = '1.5';
/** The name of the keyframes that fade the whole drawing out, which is how it reports that it has finished. */
const FADE_ANIMATION_NAME = 'basil-blueprint-fade';
/** Marks a drawing that holds only the window's outline and is waiting for the rest of the layout. It does not fade until it is completed or faded out on purpose. */
export const BLUEPRINT_PENDING_CLASS = 'basil-blueprint--pending';
const OUTLINE_CLASS = 'basil-blueprint__outline';
const FADE_DELAY_PROPERTY = '--bp-fade-delay';

function shape(tag: 'rect' | 'line', delay: string, length: string): SVGElement {
  const element = document.createElementNS(SVG_NAMESPACE, tag);
  element.setAttribute('class', 'basil-blueprint__shape');
  element.setAttribute('stroke-width', STROKE_WIDTH);
  element.style.setProperty('--bp-delay', delay);
  element.style.setProperty('--bp-len', length);
  return element;
}

function setNumbers(element: SVGElement, values: Record<string, number>): void {
  for (const [name, value] of Object.entries(values)) element.setAttribute(name, String(value));
}

function placeOutline(outline: SVGElement, frame: BlueprintOutline['frame']): void {
  setNumbers(outline, { x: frame.x, y: frame.y, width: frame.width, height: frame.height, rx: frame.radius });
  outline.style.setProperty('--bp-len', blueprintRectLength(frame));
}

function sizeDrawing(svg: SVGSVGElement, width: number, height: number): void {
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
}

/**
 * Builds a drawing that holds only the surface's outline, traced from the top left, and keeps it on screen until `completeBlueprintOverlay` adds the layout or `fadeOutBlueprintOverlay` removes it. It needs nothing but the window's size, so it can start drawing the moment the window is invoked, while its content is still loading. The drawing is decorative, never takes pointer input, and fades itself out through CSS; `onFaded` is called once that fade finishes so the caller can remove it.
 */
export function createBlueprintOutlineOverlay(outline: BlueprintOutline, onFaded: () => void): SVGSVGElement {
  const svg = document.createElementNS(SVG_NAMESPACE, 'svg');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', `basil-blueprint ${BLUEPRINT_PENDING_CLASS}`);
  sizeDrawing(svg, outline.width, outline.height);
  svg.addEventListener('animationend', (event) => {
    if (event.target === svg && (event as AnimationEvent).animationName === FADE_ANIMATION_NAME) onFaded();
  });

  const strokes = shape('rect', '0s', blueprintRectLength(outline.frame));
  strokes.classList.add(OUTLINE_CLASS);
  placeOutline(strokes, outline.frame);
  strokes.style.animationDuration = `${(0.8 * BLUEPRINT_PACE).toFixed(3)}s`;
  svg.appendChild(strokes);
  return svg;
}

/**
 * Adds the surface's parts to a drawing begun by `createBlueprintOutlineOverlay` and lets it fade out once they are drawn. The outline is corrected to the final measurement first, in case the window was resized since it was started. `warm` is true when the outline has already been on screen, so the parts start drawing at once.
 */
export function completeBlueprintOverlay(svg: SVGSVGElement, blueprint: Blueprint, warm: boolean): void {
  const { width, height } = blueprint;
  const lead = warm ? 0 : PARTS_LEAD;
  const delayFor = (centerX: number, centerY: number) => `${((lead + (centerY / height) * 0.8 + (centerX / width) * 0.1) * BLUEPRINT_PACE).toFixed(3)}s`;

  sizeDrawing(svg, width, height);
  const outline = svg.querySelector<SVGElement>(`.${OUTLINE_CLASS}`);
  if (outline) placeOutline(outline, blueprint.frame);

  for (const rect of blueprint.rects) {
    const element = shape('rect', delayFor(rect.x + rect.width / 2, rect.y + rect.height / 2), blueprintRectLength(rect));
    setNumbers(element, { x: rect.x, y: rect.y, width: rect.width, height: rect.height, rx: rect.radius });
    svg.appendChild(element);
  }

  for (const line of blueprint.lines) {
    const element = shape('line', delayFor((line.x1 + line.x2) / 2, line.y), (line.x2 - line.x1).toFixed(1));
    setNumbers(element, { x1: line.x1, x2: line.x2, y1: line.y, y2: line.y });
    element.setAttribute('stroke-linecap', 'round');
    svg.appendChild(element);
  }

  svg.style.setProperty(FADE_DELAY_PROPERTY, `${(warm ? 0.8 - PARTS_LEAD * BLUEPRINT_PACE : 0.8).toFixed(3)}s`);
  svg.classList.remove(BLUEPRINT_PENDING_CLASS);
}

/** Fades a drawing that is still waiting for its layout out at once, for a window that is being shown without a full blueprint. */
export function fadeOutBlueprintOverlay(svg: SVGSVGElement): void {
  svg.style.setProperty(FADE_DELAY_PROPERTY, '0s');
  svg.classList.remove(BLUEPRINT_PENDING_CLASS);
}

/** The whole blueprint in one go, for a window whose content was ready before any outline could be started: the outline first, then the parts. */
export function createBlueprintOverlay(blueprint: Blueprint, onFaded: () => void): SVGSVGElement {
  const svg = createBlueprintOutlineOverlay(blueprint, onFaded);
  completeBlueprintOverlay(svg, blueprint, false);
  return svg;
}
