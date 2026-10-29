// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { SuggestedFollowUps } from './SuggestedFollowUps';
import { consumeFollowUpPrefill, resetFollowUpPrefillRequests, useFollowUpPrefillRequest } from '../store/followUpPrefillStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function PrefillProbe({ taskKey }: { taskKey: string }) {
  const request = useFollowUpPrefillRequest(taskKey);
  return <div data-testid="probe">{request ? request.text : 'none'}</div>;
}

describe('SuggestedFollowUps', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    resetFollowUpPrefillRequests();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('renders nothing without suggestions', () => {
    act(() => root.render(<SuggestedFollowUps taskKey="root-1" suggestions={undefined} />));
    expect(container.innerHTML).toBe('');
    act(() => root.render(<SuggestedFollowUps taskKey="root-1" suggestions={[]} />));
    expect(container.innerHTML).toBe('');
  });

  it('asks the follow-up box to add the chosen text, and nothing else, when a chip is clicked', () => {
    act(() => root.render(
      <>
        <SuggestedFollowUps taskKey="root-1" suggestions={['Draft a reply', 'Archive the newsletters']} />
        <PrefillProbe taskKey="root-1" />
        <PrefillProbe taskKey="other-root" />
      </>,
    ));
    const chips = Array.from(container.querySelectorAll('button.suggested-follow-up-chip'));
    // The decorative check mark is aria-hidden, so the label is what remains without it.
    expect(chips.map(chip => chip.textContent?.replace('✓', ''))).toEqual(['Draft a reply', 'Archive the newsletters']);

    act(() => (chips[1] as HTMLButtonElement).click());
    const probes = Array.from(container.querySelectorAll('[data-testid="probe"]')).map(node => node.textContent);
    expect(probes).toEqual(['Archive the newsletters', 'none']);
  });

  it('lets the same chip refill the box after the previous request was consumed', () => {
    let seenNonce = 0;
    function Capture() {
      const request = useFollowUpPrefillRequest('root-1');
      if (request) seenNonce = request.nonce;
      return null;
    }
    act(() => root.render(<><SuggestedFollowUps taskKey="root-1" suggestions={['Draft a reply']} /><Capture /></>));
    const chip = container.querySelector('button.suggested-follow-up-chip') as HTMLButtonElement;

    act(() => chip.click());
    const first = seenNonce;
    act(() => consumeFollowUpPrefill('root-1', first));
    act(() => chip.click());

    expect(seenNonce).toBeGreaterThan(first);
  });
});
