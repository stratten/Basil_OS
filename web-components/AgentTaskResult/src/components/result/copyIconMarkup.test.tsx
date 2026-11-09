import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CheckmarkIcon, MarkdownCopyIcon } from './CopyButtons';
import { CHECK_ICON_MARKUP, COPY_ICON_MARKUP } from './copyIconMarkup';

describe('copy icon markup', () => {
  it('is the same drawing as the icons the result area already uses', () => {
    expect(COPY_ICON_MARKUP).toBe(renderToStaticMarkup(<MarkdownCopyIcon />));
    expect(CHECK_ICON_MARKUP).toBe(renderToStaticMarkup(<CheckmarkIcon />));
  });
});
