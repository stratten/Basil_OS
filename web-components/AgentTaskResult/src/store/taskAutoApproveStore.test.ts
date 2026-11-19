import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskAutoApproveResult } from '../types';

const mocks = vi.hoisted(() => ({
  getTaskAutoApprove: vi.fn(),
  requestTaskAutoApprove: vi.fn(),
  resultListeners: new Set<(result: TaskAutoApproveResult) => void>(),
}));

vi.mock('../services/api', () => ({ getTaskAutoApprove: mocks.getTaskAutoApprove }));

vi.mock('../services/bridge', () => ({
  requestTaskAutoApprove: mocks.requestTaskAutoApprove,
  registerTaskAutoApproveResultHandler: (listener: (result: TaskAutoApproveResult) => void) => {
    mocks.resultListeners.add(listener);
    return () => {
      mocks.resultListeners.delete(listener);
    };
  },
}));

import {
  getTaskAutoApproveState,
  loadTaskAutoApprove,
  resetTaskAutoApproveStore,
  setTaskAutoApprove,
} from './taskAutoApproveStore';

function nativeAnswers(result: Partial<TaskAutoApproveResult> & Pick<TaskAutoApproveResult, 'requestId' | 'rootTaskId'>) {
  const full: TaskAutoApproveResult = { status: 'applied', enabled: true, ...result };
  for (const listener of Array.from(mocks.resultListeners)) listener(full);
}

function lastRequest(): { requestId: string; rootTaskId: string; enabled: boolean } {
  const calls = mocks.requestTaskAutoApprove.mock.calls;
  return calls[calls.length - 1][0];
}

beforeEach(() => {
  resetTaskAutoApproveStore();
  mocks.getTaskAutoApprove.mockReset();
  mocks.getTaskAutoApprove.mockResolvedValue({ enabled: false });
  mocks.requestTaskAutoApprove.mockReset();
  mocks.resultListeners.clear();
});

describe('taskAutoApproveStore', () => {
  it('reads off for a chain nobody has touched', () => {
    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: false, error: null });
  });

  it('turning it on only asks native and leaves the switch off until native answers', () => {
    setTaskAutoApprove('root-1', true);

    expect(mocks.requestTaskAutoApprove).toHaveBeenCalledTimes(1);
    expect(lastRequest()).toEqual({ requestId: expect.any(String), rootTaskId: 'root-1', enabled: true });
    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: true, error: null });
  });

  it('applies native\'s answer: on, no longer pending', () => {
    setTaskAutoApprove('root-1', true);

    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: true });

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: true, pending: false, error: null });
  });

  it('keeps the switch off, with no error, when the user declines the confirmation', () => {
    setTaskAutoApprove('root-1', true);

    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', status: 'declined', enabled: false });

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: false, error: null });
  });

  it('keeps the switch off and says why when native could not change it', () => {
    setTaskAutoApprove('root-1', true);

    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', status: 'failed', enabled: false, message: 'Basil is not running.' });

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: false, error: 'Basil is not running.' });
  });

  it('gives a failure with no message a plain one', () => {
    setTaskAutoApprove('root-1', true);

    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', status: 'failed', enabled: false });

    expect(getTaskAutoApproveState('root-1').error).toBe('Auto-approve could not be changed.');
  });

  it('clears an earlier error when the user tries again', () => {
    setTaskAutoApprove('root-1', true);
    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', status: 'failed', enabled: false, message: 'No.' });

    setTaskAutoApprove('root-1', true);

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: true, error: null });
  });

  it('turns it off the same way once it is on', () => {
    setTaskAutoApprove('root-1', true);
    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: true });

    setTaskAutoApprove('root-1', false);
    expect(lastRequest()).toEqual({ requestId: expect.any(String), rootTaskId: 'root-1', enabled: false });
    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: false });

    expect(getTaskAutoApproveState('root-1').enabled).toBe(false);
  });

  it('sends one request at a time for a chain, and none for a state it is already in', () => {
    setTaskAutoApprove('root-1', true);
    setTaskAutoApprove('root-1', true);
    setTaskAutoApprove('root-1', false);
    expect(mocks.requestTaskAutoApprove).toHaveBeenCalledTimes(1);

    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: true });
    setTaskAutoApprove('root-1', true);
    expect(mocks.requestTaskAutoApprove).toHaveBeenCalledTimes(1);
  });

  it('keeps each chain\'s switch separate', () => {
    setTaskAutoApprove('root-1', true);
    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: true });

    expect(getTaskAutoApproveState('root-2').enabled).toBe(false);
  });

  it('ignores an answer to a request it did not make', () => {
    setTaskAutoApprove('root-1', true);

    nativeAnswers({ requestId: 'someone-elses-request', rootTaskId: 'root-1', enabled: true });

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: true, error: null });
  });

  it('applies an answer only once', () => {
    setTaskAutoApprove('root-1', true);
    const { requestId } = lastRequest();
    nativeAnswers({ requestId, rootTaskId: 'root-1', enabled: true });

    nativeAnswers({ requestId, rootTaskId: 'root-1', status: 'failed', enabled: false, message: 'Late.' });

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: true, pending: false, error: null });
  });

  it('shows a chain whose switch was turned on earlier as on, reading the backend once', async () => {
    mocks.getTaskAutoApprove.mockResolvedValue({ enabled: true });

    await loadTaskAutoApprove('root-1');
    await loadTaskAutoApprove('root-1');

    expect(mocks.getTaskAutoApprove).toHaveBeenCalledTimes(1);
    expect(mocks.getTaskAutoApprove).toHaveBeenCalledWith('root-1');
    expect(getTaskAutoApproveState('root-1').enabled).toBe(true);
  });

  it('leaves the switch off when the backend cannot be read, and tries again next time', async () => {
    mocks.getTaskAutoApprove.mockRejectedValueOnce(new Error('offline'));

    await loadTaskAutoApprove('root-1');
    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: false, error: null });

    mocks.getTaskAutoApprove.mockResolvedValueOnce({ enabled: true });
    await loadTaskAutoApprove('root-1');
    expect(getTaskAutoApproveState('root-1').enabled).toBe(true);
  });

  it('does not let a slow read overwrite a change made while it was out', async () => {
    let finishRead: (value: { enabled: boolean }) => void = () => undefined;
    mocks.getTaskAutoApprove.mockReturnValue(new Promise((resolve) => { finishRead = resolve; }));

    const reading = loadTaskAutoApprove('root-1');
    setTaskAutoApprove('root-1', true);
    finishRead({ enabled: false });
    await reading;

    expect(getTaskAutoApproveState('root-1')).toEqual({ enabled: false, pending: true, error: null });
    nativeAnswers({ requestId: lastRequest().requestId, rootTaskId: 'root-1', enabled: true });
    expect(getTaskAutoApproveState('root-1').enabled).toBe(true);
  });
});
