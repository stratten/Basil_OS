// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import type { Blueprint } from './blueprintMeasure';
import {
  BLUEPRINT_DRAW_MS,
  BLUEPRINT_PENDING_CLASS,
  BLUEPRINT_WARM_DRAW_MS,
  completeBlueprintOverlay,
  createBlueprintOutlineOverlay,
  createBlueprintOverlay,
  fadeOutBlueprintOverlay,
} from './blueprintOverlay';

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

describe('createBlueprintOverlay', () => {
  it('draws from the top down and is decorative', () => {
    const svg = createBlueprintOverlay(SAMPLE, () => {});
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('class')).toBe('basil-blueprint');
    expect(svg.getAttribute('viewBox')).toBe('0 0 300 140');

    const rects = Array.from(svg.querySelectorAll<SVGRectElement>('rect.basil-blueprint__shape'));
    expect(rects).toHaveLength(3);
    const delay = (shape: Element) => Number.parseFloat((shape as SVGElement).style.getPropertyValue('--bp-delay'));
    expect(delay(rects[1]!)).toBeLessThan(delay(rects[2]!));
    expect(rects[1]!.style.getPropertyValue('--bp-len')).not.toBe('');
    const line = svg.querySelector<SVGLineElement>('line.basil-blueprint__shape')!;
    expect(line.style.getPropertyValue('--bp-len')).toBe('120.0');
    expect(line.getAttribute('y1')).toBe('50');
    expect(line.getAttribute('stroke-linecap')).toBe('round');
  });

  it('draws the window outline first, with no delay', () => {
    const outline = createBlueprintOverlay(SAMPLE, () => {}).firstElementChild as SVGRectElement;
    expect(outline.getAttribute('x')).toBe('4');
    expect(outline.getAttribute('rx')).toBe('16');
    expect(outline.style.getPropertyValue('--bp-delay')).toBe('0s');
  });
});

describe('an outline begun before the layout is known', () => {
  const OUTLINE = { width: 300, height: 140, frame: SAMPLE.frame };
  const delay = (shape: Element) => Number.parseFloat((shape as SVGElement).style.getPropertyValue('--bp-delay'));

  it('holds only the outline and does not fade until it is completed', () => {
    const svg = createBlueprintOutlineOverlay(OUTLINE, () => {});
    expect(svg.classList.contains(BLUEPRINT_PENDING_CLASS)).toBe(true);
    expect(svg.querySelectorAll('.basil-blueprint__shape')).toHaveLength(1);
    expect(svg.getAttribute('viewBox')).toBe('0 0 300 140');
  });

  it('adds the parts to the same drawing and lets it fade', () => {
    const svg = createBlueprintOutlineOverlay(OUTLINE, () => {});
    const outline = svg.firstElementChild;
    completeBlueprintOverlay(svg, SAMPLE, true);
    expect(svg.firstElementChild).toBe(outline);
    expect(svg.querySelectorAll('.basil-blueprint__shape')).toHaveLength(4);
    expect(svg.classList.contains(BLUEPRINT_PENDING_CLASS)).toBe(false);
    expect(svg.style.getPropertyValue('--bp-fade-delay')).toBe('0.745s');
  });

  it('starts the parts at once when the outline is already on screen, and after the outline begins otherwise', () => {
    const warm = createBlueprintOutlineOverlay(OUTLINE, () => {});
    completeBlueprintOverlay(warm, SAMPLE, true);
    const cold = createBlueprintOutlineOverlay(OUTLINE, () => {});
    completeBlueprintOverlay(cold, SAMPLE, false);
    const firstPart = (svg: SVGSVGElement) => delay(svg.querySelectorAll('.basil-blueprint__shape')[1]!);
    expect(firstPart(warm)).toBeLessThan(firstPart(cold));
    expect(cold.style.getPropertyValue('--bp-fade-delay')).toBe('0.800s');
    expect(BLUEPRINT_WARM_DRAW_MS).toBeLessThan(BLUEPRINT_DRAW_MS);
  });

  it('corrects the outline to the final measurement when the window was resized meanwhile', () => {
    const svg = createBlueprintOutlineOverlay({ width: 200, height: 100, frame: { x: 4, y: 4, width: 192, height: 92, radius: 16 } }, () => {});
    completeBlueprintOverlay(svg, SAMPLE, true);
    const outline = svg.firstElementChild as SVGRectElement;
    expect(svg.getAttribute('viewBox')).toBe('0 0 300 140');
    expect(outline.getAttribute('width')).toBe('292');
    expect(outline.getAttribute('height')).toBe('132');
  });

  it('can be faded out at once without a layout', () => {
    const svg = createBlueprintOutlineOverlay(OUTLINE, () => {});
    fadeOutBlueprintOverlay(svg);
    expect(svg.classList.contains(BLUEPRINT_PENDING_CLASS)).toBe(false);
    expect(svg.style.getPropertyValue('--bp-fade-delay')).toBe('0s');
  });
});
