// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ApprovalRequestDetails from './ApprovalRequestDetails';
import type { UserInteraction } from './userInteractions';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const longCommand = `osascript -e 'tell application "Mail" to make new outgoing message with properties {subject:"Hello there"}'\nsecond line`;

const interaction: UserInteraction = {
  id: 'ap',
  entryId: 'user_interaction_ap',
  kind: 'approval',
  status: 'approved',
  prompt: longCommand,
  askedAt: '2026-10-04T23:40:02+00:00',
  respondedAt: '2026-10-04T23:41:00+00:00',
  responseHidden: false,
  options: [],
  scriptPath: '/tmp/run.scpt',
  scriptContent: 'tell application "Mail"\nactivate\nend tell',
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(<ApprovalRequestDetails interaction={interaction} />);
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const toggle = (label: RegExp) => Array.from(container.querySelectorAll<HTMLButtonElement>('button.interaction-approval-toggle')).find(button => label.test(button.textContent ?? ''));

describe('ApprovalRequestDetails expanders', () => {
  it('shows no command preview, and opens the whole command from zero height behind a Show command button', () => {
    const region = () => container.querySelector('#' + CSS.escape(toggle(/command$/)?.getAttribute('aria-controls') ?? ''));
    expect(container.querySelector('.basil-expandable-clamp')).toBeNull();
    expect(toggle(/^Show command$/)?.getAttribute('aria-expanded')).toBe('false');
    expect(region()?.classList.contains('is-collapsed')).toBe(true);
    expect(region()?.getAttribute('aria-hidden')).toBe('true');
    expect(region()?.textContent).toBe(longCommand);

    act(() => {
      toggle(/^Show command$/)?.click();
    });

    expect(toggle(/^Hide command$/)?.getAttribute('aria-expanded')).toBe('true');
    expect(region()?.classList.contains('is-collapsed')).toBe(false);
    expect(region()?.hasAttribute('aria-hidden')).toBe(false);

    act(() => {
      toggle(/^Hide command$/)?.click();
    });

    expect(toggle(/^Show command$/)?.getAttribute('aria-expanded')).toBe('false');
    expect(region()?.getAttribute('aria-hidden')).toBe('true');
  });

  it('opens and closes the script region, which stays in the page and is hidden from assistive technology while closed', () => {
    const button = () => toggle(/full script/);
    const region = () => container.querySelector('#' + CSS.escape(button()?.getAttribute('aria-controls') ?? ''));
    expect(region()?.getAttribute('aria-hidden')).toBe('true');
    expect(region()?.textContent).toContain('activate');
    expect(button()?.getAttribute('aria-controls')).toBe(region()?.id);
    expect(button()?.textContent).toContain('View full script (3 lines)');

    act(() => {
      button()?.click();
    });

    expect(region()?.hasAttribute('aria-hidden')).toBe(false);
    expect(button()?.getAttribute('aria-expanded')).toBe('true');
    expect(button()?.textContent).toContain('Hide full script');

    act(() => {
      button()?.click();
    });

    expect(region()?.getAttribute('aria-hidden')).toBe('true');
  });
});
