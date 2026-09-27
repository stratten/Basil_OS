import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it, vi } from 'vitest';

let RequestDisplay: typeof import('./RequestDisplay').default;
let hasClippedRequestContent: typeof import('./RequestDisplay').hasClippedRequestContent;

beforeAll(async () => {
  vi.stubGlobal('window', {});
  const requestDisplayModule = await import('./RequestDisplay');
  RequestDisplay = requestDisplayModule.default;
  hasClippedRequestContent = requestDisplayModule.hasClippedRequestContent;
});

vi.mock('../../services/bridge', () => ({
  openAgentTaskOrigin: vi.fn(),
}));

describe('RequestDisplay', () => {
  it('renders display Markdown through the request presentation variant', () => {
    const markup = renderToStaticMarkup(
      <RequestDisplay
        originalPrompt="Plain fallback"
        displayPromptMarkdown="**Formatted** request"
      />
    );

    expect(markup).toContain('result-section--request');
    expect(markup).toContain('<strong>Formatted</strong>');
    expect(markup).not.toContain('Plain fallback');
  });

  it('falls back to the plain prompt when no display Markdown exists', () => {
    const markup = renderToStaticMarkup(
      <RequestDisplay originalPrompt="Voice request transcript" />
    );

    expect(markup).toContain('Voice request transcript');
  });

  it('does not treat a tolerated layout remainder as hidden request text', () => {
    expect(hasClippedRequestContent(62, 60)).toBe(false);
  });

  it('detects request text that extends beyond the compact preview', () => {
    expect(hasClippedRequestContent(63, 60)).toBe(true);
  });

  it('renders the origin conversation link when conversation provenance is provided', () => {
    const markup = renderToStaticMarkup(
      <RequestDisplay
        originalPrompt="Summarize the report"
        originType="conversation"
        originId="conv-123"
      />,
    );

    expect(markup).toContain('From Conversation');
    expect(markup).toContain('request-display-origin-link');
    expect(markup).toContain('Open conversation');
  });

  it('omits the origin conversation link when originConversationId is absent', () => {
    const markup = renderToStaticMarkup(
      <RequestDisplay originalPrompt="Summarize the report" />
    );

    expect(markup).not.toContain('From Conversation');
    expect(markup).not.toContain('request-display-origin-link');
  });
});
