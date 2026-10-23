// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { RunDetailsDisclosure } from './RunDetailsDisclosure';
import type { RunDetailItem } from './resultContentUtils';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const details: RunDetailItem[] = [
  { key: 'app', label: 'Active app', value: 'Mail' },
  { key: 'toolCalls', label: 'Tool calls', value: '4' },
];

describe('RunDetailsDisclosure', () => {
  it('renders nothing without details', () => {
    expect(renderToStaticMarkup(<RunDetailsDisclosure details={[]} />)).toBe('');
  });

  it('starts collapsed with a one-line hint and expands on click', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<RunDetailsDisclosure details={details} />);
      });
      const toggle = container.querySelector<HTMLButtonElement>('button.run-details-toggle');

      expect(toggle?.getAttribute('aria-expanded')).toBe('false');
      expect(container.querySelector('.run-details-hint')?.textContent).toBe('4 tool calls · Mail');
      expect(container.querySelector('.run-details-list')).toBeNull();

      act(() => {
        toggle?.click();
      });

      expect(toggle?.getAttribute('aria-expanded')).toBe('true');
      expect(container.querySelector('.run-details-list')?.textContent).toContain('Active app');
      expect(container.querySelector('.run-details-list')?.textContent).toContain('Tool calls4');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});
