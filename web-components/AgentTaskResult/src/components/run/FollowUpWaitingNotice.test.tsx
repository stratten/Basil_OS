// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { FollowUpWaitingNotice } from './FollowUpWaitingNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

async function mountNotice(element: JSX.Element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(element);
  });
  return { container, unmount: () => act(async () => root.unmount()) };
}

const FAR_OFF = () => new Date(Date.now() + 3_600_000).toISOString();

describe('FollowUpWaitingNotice', () => {
  it('announces a far-off scheduled check with the shared circular arrow and the check time', () => {
    const markup = renderToStaticMarkup(<FollowUpWaitingNotice dueAt={new Date(Date.now() + 3_600_000).toISOString()} />);
    expect(markup).toContain('role="status"');
    expect(markup).toContain('Waiting to check again');
    expect(markup).toContain('Basil will check again automatically at');
    expect(markup).toContain('mask-image');
  });

  it('counts down to a scheduled check that is close', () => {
    const markup = renderToStaticMarkup(<FollowUpWaitingNotice dueAt={new Date(Date.now() + 150_000).toISOString()} />);
    expect(markup).toMatch(/Checking again in 2:[3-5]\d/);
    expect(markup).not.toContain('Waiting to check again');
  });

  it('counts down an in-run wait and shows why Basil is waiting', () => {
    const markup = renderToStaticMarkup(<FollowUpWaitingNotice resumeAtMs={Date.now() + 61_000} reason="The build is still running" />);
    expect(markup).toMatch(/Checking again in 1:0\d/);
    expect(markup).toContain('The build is still running');
  });

  it('says it is checking now once the time has passed', () => {
    expect(renderToStaticMarkup(<FollowUpWaitingNotice resumeAtMs={Date.now() - 5000} />)).toContain('Checking now');
    expect(renderToStaticMarkup(<FollowUpWaitingNotice dueAt={new Date(Date.now() - 5000).toISOString()} />)).toContain('Checking now');
  });

  it('renders nothing for an unparseable or missing due time', () => {
    expect(renderToStaticMarkup(<FollowUpWaitingNotice dueAt="garbage" />)).toBe('');
    expect(renderToStaticMarkup(<FollowUpWaitingNotice />)).toBe('');
  });

  it('offers Stop checking only for a scheduled check that has a stop handler', () => {
    const stop = async () => {};
    expect(renderToStaticMarkup(<FollowUpWaitingNotice dueAt={FAR_OFF()} onStopChecking={stop} />)).toContain('Stop checking');
    expect(renderToStaticMarkup(<FollowUpWaitingNotice dueAt={FAR_OFF()} />)).not.toContain('Stop checking');
    expect(renderToStaticMarkup(<FollowUpWaitingNotice resumeAtMs={Date.now() + 61_000} onStopChecking={stop} />)).not.toContain('Stop checking');
  });

  it('stops the scheduled check once when the button is clicked', async () => {
    let finish: () => void = () => {};
    const onStopChecking = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const { container, unmount } = await mountNotice(<FollowUpWaitingNotice dueAt={FAR_OFF()} onStopChecking={onStopChecking} />);
    const button = container.querySelector<HTMLButtonElement>('[data-testid="follow-up-stop-checking"]')!;

    await act(async () => { button.click(); });
    expect(button.disabled).toBe(true);
    expect(button.textContent).toBe('Stopping…');
    await act(async () => { button.click(); });
    expect(onStopChecking).toHaveBeenCalledTimes(1);

    await act(async () => { finish(); });
    expect(button.disabled).toBe(false);
    await unmount();
  });

  it('tells the user when the scheduled check could not be stopped and lets them retry', async () => {
    const onStopChecking = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(undefined);
    const { container, unmount } = await mountNotice(<FollowUpWaitingNotice dueAt={FAR_OFF()} onStopChecking={onStopChecking} />);
    const button = container.querySelector<HTMLButtonElement>('[data-testid="follow-up-stop-checking"]')!;

    await act(async () => { button.click(); });
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not stop the scheduled check. Try again.');
    expect(button.disabled).toBe(false);

    await act(async () => { button.click(); });
    expect(onStopChecking).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    await unmount();
  });
});
