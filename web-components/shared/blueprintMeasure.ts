/** A box in the frame's own pixels. The radius is already limited to what the box can show, so a round control comes out as a circle. */
export interface BlueprintRect {
  x: number;
  y: number;
  width: number;
  height: number;
  radius: number;
}

/** One line of text, drawn as a stroke through the middle of the line. */
export interface BlueprintLine {
  x1: number;
  x2: number;
  y: number;
}

/** The window's size and the surface's own outline inside it: all that can be known before the window's content has loaded. */
export interface BlueprintOutline {
  width: number;
  height: number;
  /** The surface's own outline, drawn first and around everything else, so the blueprint reads as a window being drawn even when the window holds little. */
  frame: BlueprintRect;
}

export interface Blueprint extends BlueprintOutline {
  rects: BlueprintRect[];
  lines: BlueprintLine[];
}

/** The green the blueprint is drawn in, the same as the website's scenes. */
export const BLUEPRINT_STROKE = '#22c55e';

const MAX_RECTS = 60;
const MAX_LINES = 80;
/** A large workspace window can hold thousands of elements, and the window is invisible while it is measured. Only the first of them, in document order (the top of the window, which is where the blueprint starts drawing), are looked at. */
const MAX_SCANNED_ELEMENTS = 2500;
const MAX_SCANNED_TEXT_NODES = 2500;
/** Anything smaller than this in either direction is a detail, not a part of the layout. */
const MIN_PART_PX = 14;
const NON_VISUAL = new Set(['STYLE', 'SCRIPT', 'NOSCRIPT', 'TEMPLATE']);
const CONTROLS = 'button, input, textarea, select, img, canvas, video';
/** Marks an element that is drawn as a circle without a CSS radius of its own, such as a canvas whose shader clips to a circle. Its outline is traced as a circle instead of the square box around it. */
const CIRCLE_ATTRIBUTE = 'data-blueprint-shape';

/** True when a computed color would actually show: not transparent, and not nearly so. */
function paints(color: string): boolean {
  if (color === 'transparent') return false;
  const match = color.match(/rgba?\(([^)]+)\)/);
  if (!match) return color !== '';
  const parts = (match[1] ?? '').split(/[\s,/]+/).filter(Boolean);
  const alpha = parts.length >= 4 ? Number.parseFloat(parts[3] ?? '1') : 1;
  return alpha > 0.06;
}

function near(a: BlueprintRect, b: BlueprintRect, tolerance: number): boolean {
  return Math.abs(a.x - b.x) <= tolerance && Math.abs(a.y - b.y) <= tolerance && Math.abs(a.width - b.width) <= tolerance && Math.abs(a.height - b.height) <= tolerance;
}

/** Full-bleed header and body slabs share the surface's edges. Tracing them with square corners draws a box outside the rounded window outline. */
function hugsRoundedOutline(part: BlueprintRect, outer: BlueprintRect, tolerance: number): boolean {
  const fullWidth = Math.abs(part.x - outer.x) <= tolerance && Math.abs(part.width - outer.width) <= tolerance;
  if (!fullWidth) return false;
  const touchesTop = Math.abs(part.y - outer.y) <= tolerance;
  const touchesBottom = Math.abs(part.y + part.height - (outer.y + outer.height)) <= tolerance;
  return touchesTop || touchesBottom;
}

function isShown(style: CSSStyleDeclaration): boolean {
  return style.display !== 'none' && style.opacity !== '0' && style.visibility !== 'hidden';
}

/** The length of a rounded rectangle's outline, so its stroke can be drawn by its real length. The drawing does not rely on the pathLength attribute, which some WebKit versions ignore on basic shapes. */
export function blueprintRectLength(rect: BlueprintRect): string {
  return (2 * (rect.width + rect.height) - (8 - 2 * Math.PI) * rect.radius).toFixed(1);
}

/** The frame's size and the surface's box in the frame's own pixels. Screen pixels are converted back in case the frame is scaled. Null while the frame has no layout yet. */
function readGeometry(frame: HTMLElement, content: HTMLElement) {
  const box = frame.getBoundingClientRect();
  if (box.width === 0 || frame.offsetWidth === 0) return null;
  const scale = box.width / frame.offsetWidth;
  const width = frame.offsetWidth;
  const height = frame.offsetHeight;
  const toLocal = (rect: DOMRect) => ({ x: (rect.left - box.left) / scale, y: (rect.top - box.top) / scale, width: rect.width / scale, height: rect.height / scale });
  const contentBox = toLocal(content.getBoundingClientRect());
  const outer: BlueprintRect = { ...contentBox, radius: Math.min(Number.parseFloat(getComputedStyle(content).borderTopLeftRadius) || 0, contentBox.width / 2, contentBox.height / 2) };
  return { width, height, toLocal, outer };
}

/**
 * Reads only the window's size and the surface's outline, which is known the moment the window exists, long before its content has loaded. This is what lets the blueprint start drawing at once and add the layout inside it later. Returns null while there is no layout to read.
 */
export function measureOutline(frame: HTMLElement, content: HTMLElement): BlueprintOutline | null {
  const geometry = readGeometry(frame, content);
  if (!geometry || geometry.outer.width < 1 || geometry.outer.height < 1) return null;
  return { width: geometry.width, height: geometry.height, frame: geometry.outer };
}

/**
 * Reads where a surface's own parts are, so the blueprint traces the real layout rather than a guess at it: every box that paints a fill or a border, every control and icon, and every line of text.
 * `frame` is the positioned element the blueprint is drawn inside, and `content` is the surface inside it that is being measured while it is laid out but hidden.
 * Returns null when nothing could be measured yet, so the caller can wait or give up.
 */
export function measureBlueprint(frame: HTMLElement, content: HTMLElement): Blueprint | null {
  const geometry = readGeometry(frame, content);
  if (!geometry) return null;
  const { width, height, toLocal, outer } = geometry;

  const found: Array<BlueprintRect & { control: boolean }> = [];
  for (const element of Array.from(content.querySelectorAll('*')).slice(0, MAX_SCANNED_ELEMENTS)) {
    const tag = element.tagName.toLowerCase();
    if (NON_VISUAL.has(element.tagName)) continue;
    // The inside of an icon is not a part of the layout; the icon itself is.
    if (tag !== 'svg' && element.closest('svg')) continue;
    const local = toLocal(element.getBoundingClientRect());
    if (local.width < MIN_PART_PX || local.height < MIN_PART_PX) continue;
    if (local.width > width * 0.98 && local.height > height * 0.98) continue;
    if (local.x + local.width / 2 < 0 || local.x + local.width / 2 > width || local.y + local.height / 2 < 0 || local.y + local.height / 2 > height) continue;
    const style = getComputedStyle(element);
    if (!isShown(style)) continue;
    const control = element.matches(CONTROLS) || (tag === 'svg' && local.width <= 64 && local.height <= 64);
    const filled = paints(style.backgroundColor) || (style.backgroundImage !== 'none' && style.backgroundImage !== '');
    const bordered = Number.parseFloat(style.borderTopWidth) > 0 && paints(style.borderTopColor);
    if (!control && !filled && !bordered) continue;
    const part = { ...local, radius: element.getAttribute(CIRCLE_ATTRIBUTE) === 'circle' ? Math.min(local.width, local.height) / 2 : Math.min(Number.parseFloat(style.borderTopLeftRadius) || 0, local.width / 2, local.height / 2) };
    // The surface's own box is the window itself, and a box that repeats another is drawn once.
    if (near(part, outer, 10) || hugsRoundedOutline(part, outer, 10) || found.some((other) => near(other, part, 3))) continue;
    found.push({ ...part, control });
  }
  const rects = found
    .sort((a, b) => Number(b.control) - Number(a.control) || b.width * b.height - a.width * a.height)
    .slice(0, MAX_RECTS)
    .map(({ x, y, width: w, height: h, radius }) => ({ x, y, width: w, height: h, radius }));

  const lines: BlueprintLine[] = [];
  const range = document.createRange();
  const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
  let scannedTextNodes = 0;
  for (let node = walker.nextNode(); node && scannedTextNodes < MAX_SCANNED_TEXT_NODES; node = walker.nextNode()) {
    scannedTextNodes += 1;
    const parent = node.parentElement;
    if (!parent || NON_VISUAL.has(parent.tagName) || (node.textContent ?? '').trim().length < 2) continue;
    if (!isShown(getComputedStyle(parent))) continue;
    range.selectNodeContents(node);
    for (const rect of Array.from(range.getClientRects())) {
      const local = toLocal(rect);
      if (local.width < MIN_PART_PX || local.height < 6 || local.height > 60) continue;
      const middle = local.y + local.height / 2;
      if (middle < 0 || middle > height || local.x + local.width < 0 || local.x > width) continue;
      lines.push({ x1: Math.max(0, local.x) + 1, x2: Math.min(width, local.x + local.width) - 1, y: middle });
    }
  }
  const step = lines.length / MAX_LINES;
  const sampled = lines.length > MAX_LINES ? Array.from({ length: MAX_LINES }, (_, index) => lines[Math.floor(index * step)] as BlueprintLine) : lines;

  if (rects.length === 0 && sampled.length === 0) return null;
  return { width, height, rects, lines: sampled, frame: outer };
}
