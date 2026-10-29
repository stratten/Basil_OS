import { describe, expect, it, vi } from 'vitest';
import { createFilePreviewRequestManager, type FilePreviewPayload } from './artifactPreviewTransport';

function harness() {
  const postMessage = vi.fn();
  let readyHandler: ((payload: FilePreviewPayload) => void) | undefined;
  let updatedHandler: ((payload: FilePreviewPayload) => void) | undefined;
  const transport = createFilePreviewRequestManager(
    postMessage,
    (cb) => {
      readyHandler = cb;
      return () => {
        if (readyHandler === cb) readyHandler = undefined;
      };
    },
    (cb) => {
      updatedHandler = cb;
      return () => {
        if (updatedHandler === cb) updatedHandler = undefined;
      };
    },
  );
  return {
    postMessage,
    transport,
    emitReady: (payload: FilePreviewPayload) => readyHandler?.(payload),
    emitUpdated: (payload: FilePreviewPayload) => updatedHandler?.(payload),
  };
}

describe('createFilePreviewRequestManager', () => {
  it('resolves previewFile with the matching ready payload and posts one previewFile message', async () => {
    const { transport, postMessage, emitReady } = harness();
    const promise = transport.previewFile('/tmp/report.md');
    const sent = postMessage.mock.calls[0]?.[0];
    expect(sent).toMatchObject({ type: 'previewFile', path: '/tmp/report.md' });

    emitReady({ requestId: sent.requestId, path: '/tmp/report.md', name: 'report.md', kind: 'markdown', content: '# Hi' });

    await expect(promise).resolves.toMatchObject({ kind: 'markdown', content: '# Hi' });
  });

  it('supersedes a pending preview when another file is requested', async () => {
    const { transport, postMessage, emitReady } = harness();
    const first = transport.previewFile('/tmp/first.md');
    const firstRejection = expect(first).rejects.toThrow('File preview request was superseded by a new request.');
    const second = transport.previewFile('/tmp/second.md');
    const firstId = postMessage.mock.calls[0][0].requestId;
    const secondId = postMessage.mock.calls[1][0].requestId;
    expect(firstId).not.toBe(secondId);

    await firstRejection;

    emitReady({ requestId: secondId, path: '/tmp/second.md', name: 'second.md', kind: 'text', content: 'second' });
    await expect(second).resolves.toMatchObject({ content: 'second' });

    emitReady({ requestId: firstId, path: '/tmp/first.md', name: 'first.md', kind: 'text', content: 'first' });
  });

  it('rejects with a timeout error and drops a ready payload that arrives after the timeout', async () => {
    vi.useFakeTimers();
    try {
      const { transport, postMessage, emitReady } = harness();
      const promise = transport.previewFile('/tmp/slow.md');
      const requestId = postMessage.mock.calls[0][0].requestId;

      const assertion = expect(promise).rejects.toThrow('File preview request timed out.');
      await vi.advanceTimersByTimeAsync(10000);
      await assertion;

      expect(() => emitReady({ requestId, path: '/tmp/slow.md', name: 'slow.md', kind: 'text', content: 'late' })).not.toThrow();
    } finally {
      vi.useRealTimers();
    }
  });

  it('clearFilePreview rejects a pending request, posts clearFilePreview, and does not invoke the update handler', async () => {
    vi.useFakeTimers();
    try {
      const { transport, postMessage } = harness();
      const preview = transport.previewFile('/tmp/report.md');
      const rejection = expect(preview).rejects.toThrow('File preview request was cleared.');
      const requestId = postMessage.mock.calls[0][0].requestId;
      const updateHandler = vi.fn();
      transport.registerFilePreviewUpdateHandler(updateHandler);

      transport.clearFilePreview(requestId);
      await rejection;
      expect(postMessage).toHaveBeenLastCalledWith({ type: 'clearFilePreview', requestId });

      vi.advanceTimersByTime(10000);
      expect(updateHandler).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('registerFilePreviewUpdateHandler delivers live updates and its unsubscribe stops delivery', () => {
    const { transport, emitUpdated } = harness();
    const handler = vi.fn();
    const unsubscribe = transport.registerFilePreviewUpdateHandler(handler);

    emitUpdated({ requestId: 'req-1', path: '/tmp/report.md', name: 'report.md', kind: 'text', content: 'v1' });
    expect(handler).toHaveBeenCalledTimes(1);

    unsubscribe();
    emitUpdated({ requestId: 'req-1', path: '/tmp/report.md', name: 'report.md', kind: 'text', content: 'v2' });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('forwards setInlineNativePreviewFrame, hideInlineNativePreview, and clearInlineNativePreview verbatim', () => {
    const { transport, postMessage } = harness();
    const frame = { left: 0, top: 0, width: 10, height: 10, viewportWidth: 100, viewportHeight: 100 };

    transport.setInlineNativePreviewFrame('req-1', frame);
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'setInlineNativePreviewFrame', requestId: 'req-1', frame });

    transport.hideInlineNativePreview('req-1');
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'hideInlineNativePreview', requestId: 'req-1' });

    transport.clearInlineNativePreview('req-1');
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'clearInlineNativePreview', requestId: 'req-1' });
  });
});
