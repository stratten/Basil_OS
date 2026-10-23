import { describe, expect, it } from 'vitest';

import {
  AGENT_TASK_COMPACT_HEIGHT,
  AGENT_TASK_COMPACT_WIDTH,
  measureCollapsedHeaderSize,
} from './collapsedHeaderSizing';

describe('measureCollapsedHeaderSize', () => {
  it('returns the fixed collapsed size when there is no header element', () => {
    expect(measureCollapsedHeaderSize(null)).toEqual({
      width: AGENT_TASK_COMPACT_WIDTH,
      height: AGENT_TASK_COMPACT_HEIGHT,
    });
  });

  // The collapsed size is intentionally fixed: header content (long titles,
  // volatile status lines) must never drive the width, since that drift was the
  // "shifting" the fixed width was introduced to remove.
  it('stays fixed regardless of header content width', () => {
    const header = { scrollWidth: 900, offsetHeight: 68 } as unknown as HTMLElement;
    expect(measureCollapsedHeaderSize(header)).toEqual({
      width: AGENT_TASK_COMPACT_WIDTH,
      height: AGENT_TASK_COMPACT_HEIGHT,
    });
  });
});
