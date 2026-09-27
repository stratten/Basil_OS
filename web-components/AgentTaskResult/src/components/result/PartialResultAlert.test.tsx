import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it, vi } from 'vitest';

let PartialResultAlert: typeof import('./PartialResultAlert').PartialResultAlert;

beforeAll(async () => {
  vi.stubGlobal('window', {});
  PartialResultAlert = (await import('./PartialResultAlert')).PartialResultAlert;
});

describe('PartialResultAlert disclosure', () => {
  it('points right while the result detail is hidden', () => {
    const markup = renderToStaticMarkup(
      <PartialResultAlert message="Partial result" isCollapsed onToggle={() => {}} />
    );

    expect(markup).toContain('transform:rotate(-90deg)');
  });

  it('points down while the result detail is visible', () => {
    const markup = renderToStaticMarkup(
      <PartialResultAlert message="Partial result" isCollapsed={false} onToggle={() => {}} />
    );

    expect(markup).toContain('transform:rotate(0deg)');
  });

  it('does not render the obsolete completed-with-warnings state', () => {
    const markup = renderToStaticMarkup(
      <PartialResultAlert
        message="Recovered retry detail"
        outcome="completed_with_warnings"
        severity="warning"
        isCollapsed
        onToggle={() => {}}
      />
    );

    expect(markup).toBe('');
  });
});
