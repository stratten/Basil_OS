import { describe, expect, it } from 'vitest';
import {
  measureContentAreaLayoutHeight,
  measureExpandedWidgetContentHeight,
  measureOverlayDialogIntrinsicHeight,
  measureScrollRegionIntrinsicHeight,
  measureStableScrollRegionHeight,
} from './resultWidgetSizing';

describe('measureContentAreaLayoutHeight', () => {
  it('sums non-absolute child offset heights', () => {
    const contentArea = {
      children: [
        { offsetHeight: 120 },
        { offsetHeight: 54 },
      ],
    };

    expect(measureContentAreaLayoutHeight(contentArea, () => false)).toBe(174);
  });

  it('ignores absolutely positioned children such as progress overlays', () => {
    const contentArea = {
      children: [
        { offsetHeight: 120 },
        { offsetHeight: 40 },
      ],
    };

    expect(
      measureContentAreaLayoutHeight(
        contentArea,
        element => element === contentArea.children[1],
      ),
    ).toBe(120);
  });

  it('falls back when no measurable children exist', () => {
    expect(measureContentAreaLayoutHeight({ children: [] }, () => false)).toBe(144);
    expect(measureContentAreaLayoutHeight(null, () => false)).toBe(144);
  });
});

describe('measureOverlayDialogIntrinsicHeight', () => {
  it('uses scroll height when a capped dialog has hidden intrinsic overflow', () => {
    expect(
      measureOverlayDialogIntrinsicHeight({ offsetHeight: 248, scrollHeight: 388 }),
    ).toBe(388);
  });

  it('uses the laid-out height when the dialog has no overflow', () => {
    expect(
      measureOverlayDialogIntrinsicHeight({ offsetHeight: 248, scrollHeight: 248 }),
    ).toBe(248);
  });

  it('adds the clipped overflow of the question and option scroll regions', () => {
    const regions = [
      { scrollHeight: 420, clientHeight: 120 },
      { scrollHeight: 260, clientHeight: 80 },
    ];
    const querySelectorAll = (selector: string) => {
      expect(selector).toBe('.checkpoint-prompt-details, .checkpoint-response-scroll-region');
      return regions;
    };
    expect(
      measureOverlayDialogIntrinsicHeight({ offsetHeight: 300, scrollHeight: 300, querySelectorAll }),
    ).toBe(300 + 300 + 180);
  });

  it('keeps the measurement stable once the window has grown enough to show every region in full', () => {
    const querySelectorAll = () => [
      { scrollHeight: 420, clientHeight: 420 },
      { scrollHeight: 260, clientHeight: 260 },
    ];
    expect(
      measureOverlayDialogIntrinsicHeight({ offsetHeight: 780, scrollHeight: 780, querySelectorAll }),
    ).toBe(780);
  });

  it('returns zero when the dialog is absent or unmeasurable', () => {
    expect(measureOverlayDialogIntrinsicHeight(null)).toBe(0);
    expect(measureOverlayDialogIntrinsicHeight({})).toBe(0);
  });
});

describe('measureScrollRegionIntrinsicHeight', () => {
  it('sums visible child block heights instead of scroll overflow', () => {
    const scrollRegion = {
      children: [
        { offsetHeight: 48 },
        { offsetHeight: 72 },
      ],
    };

    expect(measureScrollRegionIntrinsicHeight(scrollRegion)).toBe(120);
  });
});

describe('measureStableScrollRegionHeight', () => {
  it('excludes reasoning height while retaining all other scroll content', () => {
    const reasoning = {
      classList: { contains: (value: string) => value === 'thinking-segments' },
      offsetHeight: 240,
    };
    const result = {
      classList: { contains: () => false },
      offsetHeight: 180,
    };
    const scrollRegion = {
      children: [reasoning, result],
    };

    expect(measureStableScrollRegionHeight(scrollRegion)).toBe(180);
    reasoning.offsetHeight = 320;
    expect(measureStableScrollRegionHeight(scrollRegion)).toBe(180);
  });
});

describe('measureExpandedWidgetContentHeight', () => {
  it('includes dock height and visible main-content blocks from the result shell', () => {
    const mainContent = {
      classList: { contains: (value: string) => value === 'main-content' },
      children: [{ offsetHeight: 180 }, { offsetHeight: 64 }],
    };
    const dock = { classList: { contains: () => false }, offsetHeight: 54 };
    const shell = {
      matches: () => true,
      querySelector: () => null,
      children: [mainContent, dock],
    };
    const contentArea = {
      children: [shell],
    };

    expect(
      measureExpandedWidgetContentHeight({
        contentArea,
        mainContent,
      }),
    ).toBe(298);
  });
});
