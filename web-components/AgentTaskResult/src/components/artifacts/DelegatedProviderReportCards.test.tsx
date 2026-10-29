// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { DelegatedProviderReportCard } from '../../artifacts/artifactContract';
import { DelegatedProviderReportCards } from './DelegatedProviderReportCards';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const cards: DelegatedProviderReportCard[] = [
  {
    delegatedAgentRunId: 'run-private-1',
    runStatus: 'supervision_due',
    runRevision: 4,
    captureState: 'available',
    evidenceCount: 25,
    latestSummary: 'Provider completed this turn.',
    verificationState: 'not_applicable',
  },
  {
    delegatedAgentRunId: 'run-private-2',
    runStatus: 'settled',
    runRevision: 7,
    captureState: 'available',
    evidenceCount: 26,
    latestSummary: 'Verified workspace artifact.',
    verificationState: 'verified',
  },
];

describe('DelegatedProviderReportCards', () => {
  it('renders one compact aggregate chip without provider detail', () => {
    const markup = renderToStaticMarkup(<DelegatedProviderReportCards cards={cards} />);
    for (const text of ['Delegated work', '2 runs', 'In progress', 'delegated-provider-work-chip--working']) {
      expect(markup).toContain(text);
    }
    for (const text of ['run-private-1', 'supervision due', '25', 'Provider completed this turn.', 'Verified workspace artifact.', 'verified']) {
      expect(markup).not.toContain(text);
    }
  });

  it('summarizes failed capture or verification as needing review', () => {
    const markup = renderToStaticMarkup(
      <DelegatedProviderReportCards cards={[{
        delegatedAgentRunId: 'run-private-3',
        runStatus: 'failed',
        runRevision: 2,
        captureState: 'unavailable',
        evidenceCount: 0,
        verificationState: 'verification_mismatch',
      }]} />,
    );
    expect(markup).toContain('Needs review');
    expect(markup).toContain('delegated-provider-work-chip--review');
  });

  it('returns no markup without cards', () => {
    expect(renderToStaticMarkup(<DelegatedProviderReportCards cards={[]} />)).toBe('');
  });

  it('reveals concise per-run status only after the chip is activated', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<DelegatedProviderReportCards cards={cards} />);
      });
      const toggle = container.querySelector<HTMLButtonElement>('.delegated-provider-work-chip-toggle');
      expect(toggle?.getAttribute('aria-expanded')).toBe('false');
      expect(container.textContent).not.toContain('Provider completed this turn.');

      act(() => {
        toggle?.click();
      });
      expect(toggle?.getAttribute('aria-expanded')).toBe('true');
      expect(container.textContent).toContain('Provider run 1');
      expect(container.textContent).toContain('Provider completed this turn.');
      expect(container.textContent).not.toContain('run-private-1');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('flattens markdown in the per-run summary', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<DelegatedProviderReportCards cards={[{ ...cards[0], latestSummary: 'Updated **README** in `docs/`' }]} />);
      });
      act(() => {
        container.querySelector<HTMLButtonElement>('.delegated-provider-work-chip-toggle')?.click();
      });
      expect(container.querySelector('.delegated-provider-work-details-summary')?.textContent).toBe('Updated README in docs/');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('summarizes fully verified work as verified', () => {
    const markup = renderToStaticMarkup(
      <DelegatedProviderReportCards cards={[{
        ...cards[1],
        delegatedAgentRunId: 'run-private-verified',
      }]} />,
    );

    expect(markup).toContain('Verified');
    expect(markup).toContain('delegated-provider-work-chip--verified');
  });
});
