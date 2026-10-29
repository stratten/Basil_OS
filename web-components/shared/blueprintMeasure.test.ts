// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { blueprintRectLength, measureBlueprint } from './blueprintMeasure';

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

const elementBoxes = new Map<Element, Box>();
const textBoxes = new Map<Node, Box[]>();

function domRect({ left, top, width, height }: Box): DOMRect {
  return { x: left, y: top, left, top, width, height, right: left + width, bottom: top + height, toJSON: () => ({}) } as DOMRect;
}

function place(element: Element, box: Box) {
  elementBoxes.set(element, box);
}

function build(html: string): { frame: HTMLElement; content: HTMLElement } {
  const frame = document.createElement('div');
  const content = document.createElement('div');
  content.innerHTML = html;
  frame.appendChild(content);
  document.body.appendChild(frame);
  Object.defineProperty(frame, 'offsetWidth', { configurable: true, value: 300 });
  Object.defineProperty(frame, 'offsetHeight', { configurable: true, value: 140 });
  place(frame, { left: 0, top: 0, width: 300, height: 140 });
  place(content, { left: 4, top: 4, width: 292, height: 132 });
  return { frame, content };
}

beforeEach(() => {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    return domRect(elementBoxes.get(this) ?? { left: 0, top: 0, width: 0, height: 0 });
  });
  Object.defineProperty(Range.prototype, 'getClientRects', {
    configurable: true,
    value(this: Range) {
      return (textBoxes.get(this.startContainer) ?? []).map(domRect);
    },
  });
});

afterEach(() => {
  elementBoxes.clear();
  textBoxes.clear();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('measureBlueprint', () => {
  it('returns null while the frame has no size', () => {
    const { frame, content } = build('<button>Go</button>');
    place(frame, { left: 0, top: 0, width: 0, height: 0 });
    expect(measureBlueprint(frame, content)).toBeNull();
  });

  it('returns null when nothing in the content paints or reads', () => {
    const { frame, content } = build('<div></div>');
    place(content.firstElementChild!, { left: 20, top: 20, width: 100, height: 40 });
    expect(measureBlueprint(frame, content)).toBeNull();
  });

  it('reports the content\'s own box and corner radius as the outline of the whole surface', () => {
    const { frame, content } = build('<button>Go</button>');
    content.style.borderTopLeftRadius = '16px';
    place(content.firstElementChild!, { left: 20, top: 20, width: 60, height: 24 });

    expect(measureBlueprint(frame, content)!.frame).toEqual({ x: 4, y: 4, width: 292, height: 132, radius: 16 });
  });

  it('traces filled boxes, controls, and lines of text in the frame\'s own pixels', () => {
    const { frame, content } = build('<div style="background-color: rgb(10, 20, 30); border-top-left-radius: 8px"></div><button>Go</button><p>Hello there</p>');
    const [card, button, paragraph] = Array.from(content.children);
    place(card!, { left: 20, top: 30, width: 120, height: 50 });
    place(button!, { left: 160, top: 90, width: 60, height: 24 });
    place(paragraph!, { left: 20, top: 100, width: 100, height: 16 });
    textBoxes.set(paragraph!.firstChild!, [{ left: 20, top: 100, width: 80, height: 16 }]);

    const blueprint = measureBlueprint(frame, content);

    expect(blueprint).not.toBeNull();
    expect(blueprint!.width).toBe(300);
    expect(blueprint!.height).toBe(140);
    expect(blueprint!.rects).toEqual([
      { x: 160, y: 90, width: 60, height: 24, radius: 0 },
      { x: 20, y: 30, width: 120, height: 50, radius: 8 },
    ]);
    expect(blueprint!.lines).toEqual([{ x1: 21, x2: 99, y: 108 }]);
  });

  it('traces a canvas marked as a circle as a circle, and an unmarked canvas as its own box', () => {
    const { frame, content } = build('<canvas data-blueprint-shape="circle"></canvas><canvas></canvas>');
    const [bubble, plain] = Array.from(content.children);
    place(bubble!, { left: 20, top: 30, width: 44, height: 44 });
    place(plain!, { left: 120, top: 30, width: 44, height: 44 });

    expect(measureBlueprint(frame, content)!.rects).toEqual([
      { x: 20, y: 30, width: 44, height: 44, radius: 22 },
      { x: 120, y: 30, width: 44, height: 44, radius: 0 },
    ]);
  });

  it('skips full-bleed header and body slabs so their square corners do not sit outside the rounded outline', () => {
    const { frame, content } = build(
      '<div style="background-color: rgb(1, 2, 3)"></div><div style="background-color: rgb(4, 5, 6)"></div><div style="background-color: rgb(7, 8, 9)"></div>',
    );
    content.style.borderTopLeftRadius = '16px';
    const [header, body, card] = Array.from(content.children);
    place(header!, { left: 4, top: 4, width: 292, height: 44 });
    place(body!, { left: 4, top: 48, width: 292, height: 88 });
    place(card!, { left: 24, top: 64, width: 80, height: 30 });

    expect(measureBlueprint(frame, content)!.rects).toEqual([{ x: 24, y: 64, width: 80, height: 30, radius: 0 }]);
  });

  it('skips tiny parts, the content\'s own box, repeated boxes, and anything hidden', () => {
    const { frame, content } = build(
      '<button>tiny</button><div style="background-color: rgb(1, 2, 3)"></div><div style="background-color: rgb(1, 2, 3)"></div><button style="display: none">hidden</button><button style="opacity: 0">clear</button><div style="background-color: rgb(9, 9, 9)"></div><button>Keep</button>',
    );
    const [tiny, firstFill, duplicateFill, hiddenByDisplay, hiddenByOpacity, wholeWindow, keep] = Array.from(content.children);
    place(tiny!, { left: 10, top: 10, width: 8, height: 8 });
    place(firstFill!, { left: 30, top: 30, width: 100, height: 40 });
    place(duplicateFill!, { left: 31, top: 31, width: 100, height: 40 });
    place(hiddenByDisplay!, { left: 150, top: 30, width: 60, height: 24 });
    place(hiddenByOpacity!, { left: 150, top: 60, width: 60, height: 24 });
    place(wholeWindow!, { left: 4, top: 4, width: 292, height: 132 });
    place(keep!, { left: 150, top: 100, width: 60, height: 24 });

    const blueprint = measureBlueprint(frame, content);

    expect(blueprint!.rects.map((rect) => [rect.x, rect.y])).toEqual([[150, 100], [30, 30]]);
  });

  it('ignores the inside of an icon but keeps the icon', () => {
    const { frame, content } = build('<svg><rect id="inner" style="background-color: rgb(1, 2, 3)"></rect></svg>');
    const icon = content.querySelector('svg')!;
    place(icon, { left: 20, top: 20, width: 24, height: 24 });
    place(content.querySelector('#inner')!, { left: 22, top: 22, width: 20, height: 20 });

    expect(measureBlueprint(frame, content)!.rects).toEqual([{ x: 20, y: 20, width: 24, height: 24, radius: 0 }]);
  });

  it('converts screen pixels back to the frame\'s own pixels when the frame is scaled', () => {
    const { frame, content } = build('<button>Go</button>');
    place(frame, { left: 100, top: 50, width: 150, height: 70 });
    place(content.firstElementChild!, { left: 100 + 30, top: 50 + 20, width: 60, height: 30 });

    expect(measureBlueprint(frame, content)!.rects).toEqual([{ x: 60, y: 40, width: 120, height: 60, radius: 0 }]);
  });

  it('caps the number of boxes and lines', () => {
    const buttons = Array.from({ length: 70 }, () => '<button>b</button>').join('');
    const paragraphs = Array.from({ length: 100 }, () => '<p>some text</p>').join('');
    const { frame, content } = build(buttons + paragraphs);
    Array.from(content.children).forEach((child, index) => {
      place(child, { left: 10 + (index % 10) * 20, top: 10 + Math.floor(index / 10) * 10, width: 18, height: 16 });
      if (child.tagName === 'P') textBoxes.set(child.firstChild!, [{ left: 10 + (index % 10) * 20, top: 10 + Math.floor(index / 10) * 10, width: 18, height: 16 }]);
    });

    const blueprint = measureBlueprint(frame, content)!;

    expect(blueprint.rects.length).toBeLessThanOrEqual(60);
    expect(blueprint.lines.length).toBeLessThanOrEqual(80);
  });
});

describe('measureBlueprint on a very large window', () => {
  it('only looks at the first elements in document order, so a heavy window is measured quickly', () => {
    const early = '<button>early</button>';
    const filler = Array.from({ length: 2600 }, () => '<span></span>').join('');
    const late = '<button>late</button>';
    const { frame, content } = build(early + filler + late);
    const buttons = Array.from(content.querySelectorAll('button'));
    place(buttons[0]!, { left: 10, top: 10, width: 60, height: 24 });
    place(buttons[1]!, { left: 10, top: 60, width: 60, height: 24 });

    const blueprint = measureBlueprint(frame, content)!;

    expect(blueprint.rects).toEqual([{ x: 10, y: 10, width: 60, height: 24, radius: 0 }]);
  });
});

describe('blueprintRectLength', () => {
  it('measures a square-cornered rectangle by its perimeter', () => {
    expect(blueprintRectLength({ x: 0, y: 0, width: 100, height: 50, radius: 0 })).toBe('300.0');
  });

  it('measures a circle by its circumference', () => {
    expect(blueprintRectLength({ x: 0, y: 0, width: 20, height: 20, radius: 10 })).toBe((2 * Math.PI * 10).toFixed(1));
  });
});
