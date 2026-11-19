import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ExecutionDisclosureChevron from './ExecutionDisclosureChevron';

describe('ExecutionDisclosureChevron', () => {
  it('points right while minimized', () => {
    const markup = renderToStaticMarkup(<ExecutionDisclosureChevron expanded={false} />);

    expect(markup).toContain('transform:rotate(-90deg)');
  });

  it('points down while expanded', () => {
    const markup = renderToStaticMarkup(<ExecutionDisclosureChevron expanded />);

    expect(markup).toContain('transform:rotate(0deg)');
  });
});
