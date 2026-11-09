import { beforeEach, describe, expect, it, vi } from 'vitest';

// The module mock forwards to a swappable implementation so one test can reject with a plain string through an ordinary function, which the vitest spy layer reports as an unhandled error when it is a spy.
const { runScheduledAgentTaskNow, forwarder } = vi.hoisted(() => {
  const spy = vi.fn();
  return { runScheduledAgentTaskNow: spy, forwarder: { current: spy as (id: string) => unknown } };
});

vi.mock('./api', () => ({ runScheduledAgentTaskNow: (id: string) => forwarder.current(id) }));

import { startScheduledRunNow } from './scheduledRunNow';

describe('startScheduledRunNow', () => {
  beforeEach(() => {
    runScheduledAgentTaskNow.mockReset();
    forwarder.current = runScheduledAgentTaskNow;
  });

  it('reports a run that started', async () => {
    runScheduledAgentTaskNow.mockResolvedValue({ success: true, run_id: 'run-1' });

    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: true });
    expect(runScheduledAgentTaskNow).toHaveBeenCalledWith('schedule-1');
  });

  it('turns the success false response into a failure carrying the backend reason', async () => {
    runScheduledAgentTaskNow.mockResolvedValue({ success: false, error: '  Scheduled task not found  ' });

    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: false, message: 'Scheduled task not found' });
  });

  it('words a failure that came with no reason', async () => {
    runScheduledAgentTaskNow.mockResolvedValue({ success: false });
    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: false, message: 'Basil could not start this run. Try again.' });

    runScheduledAgentTaskNow.mockResolvedValue({ success: false, error: '   ' });
    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: false, message: 'Basil could not start this run. Try again.' });
  });

  it('turns a failed request into a failure carrying its message instead of throwing', async () => {
    runScheduledAgentTaskNow.mockRejectedValue(new Error('offline'));

    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: false, message: 'offline' });
  });

  it('uses the plain wording when the failure carries no message', async () => {
    forwarder.current = () => Promise.reject('boom');

    await expect(startScheduledRunNow('schedule-1')).resolves.toEqual({ ok: false, message: 'Basil could not start this run. Try again.' });
  });
});
