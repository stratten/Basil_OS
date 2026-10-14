// @vitest-environment jsdom

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { FollowUpWaitingNotice } from './FollowUpWaitingNotice';

describe('FollowUpWaitingNotice', () => {
  it('announces the waiting state with the shared circular arrow and the check time', () => {
    const markup = renderToStaticMarkup(<FollowUpWaitingNotice dueAt={new Date(Date.now() + 3_600_000).toISOString()} />);
    expect(markup).toContain('role="status"');
    expect(markup).toContain('Waiting to check again');
    expect(markup).toContain('Basil will check again automatically at');
    expect(markup).toContain('mask-image');
  });

  it('renders nothing for an unparseable due time', () => {
    expect(renderToStaticMarkup(<FollowUpWaitingNotice dueAt="garbage" />)).toBe('');
  });
});
