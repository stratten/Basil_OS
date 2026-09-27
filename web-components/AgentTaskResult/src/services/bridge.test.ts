// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import {
  buildLocalServerPreview,
  buildStaticLocalWebPreview,
  checkFilePreviewAvailability,
  clearFilePreview,
  __resetCaptureStateBridgeForTests,
  openAgentTaskOrigin,
  openFilePreviewWindow,
  reportAgentStatus,
  requestResize,
  registerCaptureHandler,
  registerExpandChromeForTaskCompletionHandler,
  registerShowScheduledAgentTaskHandler,
  registerValidationManagedHistoryRestoreHandler,
  registerValidationRunFocusHandler,
  registerValidationRunStateRequestHandler,
  previewFile,
  reportValidationRunFocused,
} from './bridge';

const { publishCaptureMeter } = vi.hoisted(() => ({
  publishCaptureMeter: vi.fn(),
}));

vi.mock('../store/captureMeterStore', () => ({
  publishCaptureMeter,
}));

describe('capture state bridge', () => {
  it('publishes every meter tick but forwards only semantic capture changes', () => {
    __resetCaptureStateBridgeForTests();
    const captureHandler = vi.fn();
    registerCaptureHandler(captureHandler);
    const initial = {
      type: 'followUp' as const,
      isCapturing: true,
      wordsDetected: '',
      audioLevel: 0.2,
      silenceProgress: 0,
    };

    window.basilAgentTask?.onCaptureStateChanged(initial);
    window.basilAgentTask?.onCaptureStateChanged({ ...initial, audioLevel: 0.7 });
    window.basilAgentTask?.onCaptureStateChanged({
      ...initial,
      audioLevel: 0.8,
      wordsDetected: 'Schedule a meeting',
    });

    expect(publishCaptureMeter).toHaveBeenNthCalledWith(1, 0.2);
    expect(publishCaptureMeter).toHaveBeenNthCalledWith(2, 0.7);
    expect(publishCaptureMeter).toHaveBeenNthCalledWith(3, 0.8);
    expect(captureHandler).toHaveBeenCalledTimes(2);
    expect(captureHandler).toHaveBeenLastCalledWith({
      ...initial,
      audioLevel: 0.8,
      wordsDetected: 'Schedule a meeting',
    });
  });
});

describe('file preview availability bridge', () => {
  it('asks the native host once per unique path and resolves the confirmed paths', async () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    const request = checkFilePreviewAvailability([
      '/private/reports/present.md',
      '/private/reports/present.md',
      '/private/reports/missing.md',
    ]);
    const message = postMessage.mock.calls[0]?.[0];

    expect(message).toMatchObject({
      type: 'checkFilePreviewAvailability',
      paths: ['/private/reports/present.md', '/private/reports/missing.md'],
    });

    window.basilAgentTask?.onFilePreviewAvailability({
      requestId: message.requestId,
      availablePaths: ['/private/reports/present.md'],
    });

    await expect(request).resolves.toEqual(new Set(['/private/reports/present.md']));
  });
});

describe('agent task origin bridge', () => {
  it('posts a typed origin navigation payload to the native host', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    openAgentTaskOrigin('todo', 'todo-123');

    expect(postMessage).toHaveBeenCalledWith({
      type: 'openAgentTaskOrigin',
      originType: 'todo',
      originId: 'todo-123',
    });
  });

  it('queues a scheduled-task deep link until the application handler registers', () => {
    const handler = vi.fn();

    window.basilAgentTask?.showScheduledAgentTask('schedule-1');
    registerShowScheduledAgentTaskHandler(handler);

    expect(handler).toHaveBeenCalledWith('schedule-1');
  });
});

describe('agent task completion chrome bridge', () => {
  it('queues native expansion until React registers and delivers later commands immediately', () => {
    const handler = vi.fn();

    window.basilAgentTask?.onExpandChromeForTaskCompletion();
    registerExpandChromeForTaskCompletionHandler(handler);

    expect(handler).toHaveBeenCalledTimes(1);

    window.basilAgentTask?.onExpandChromeForTaskCompletion();

    expect(handler).toHaveBeenCalledTimes(2);
  });

  it('reports a terminal state separately from result presence', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    reportAgentStatus(false, true, false, 'task-awaiting-input', true);

    expect(postMessage).toHaveBeenCalledWith({
      type: 'agentStatusChanged',
      isProcessing: false,
      hasResult: true,
      isTerminal: false,
      agentTaskId: 'task-awaiting-input',
      supportsFollowUp: true,
    });
  });
});

describe('validation run-focus bridge', () => {
  it('queues a managed-history restore request until the visible review control registers', () => {
    const restoreHandler = vi.fn();

    window.basilAgentTask?.onRestoreValidationManagedHistory('restore-before-registration');
    const unregisterRestore = registerValidationManagedHistoryRestoreHandler(restoreHandler);

    expect(restoreHandler).toHaveBeenCalledWith('restore-before-registration');
    unregisterRestore();
  });

  it('queues state and focus commands received before React registers', () => {
    const stateHandler = vi.fn();
    const focusHandler = vi.fn();

    window.basilAgentTask?.onRequestValidationRunState('state-before-registration');
    window.basilAgentTask?.onFocusValidationRun({
      requestId: 'focus-before-registration',
      runId: 'validation-run-history-root',
    });
    const unregisterState = registerValidationRunStateRequestHandler(stateHandler);
    const unregisterFocus = registerValidationRunFocusHandler(focusHandler);

    expect(stateHandler).toHaveBeenCalledWith('state-before-registration');
    expect(focusHandler).toHaveBeenCalledWith({
      requestId: 'focus-before-registration',
      runId: 'validation-run-history-root',
    });
    unregisterState();
    unregisterFocus();
  });

  it('dispatches registered state and focus commands immediately', () => {
    const stateHandler = vi.fn();
    const focusHandler = vi.fn();
    const unregisterState = registerValidationRunStateRequestHandler(stateHandler);
    const unregisterFocus = registerValidationRunFocusHandler(focusHandler);

    window.basilAgentTask?.onRequestValidationRunState('state-immediate');
    window.basilAgentTask?.onFocusValidationRun({
      requestId: 'focus-immediate',
      runId: 'validation-run-history-follow-up-2',
    });

    expect(stateHandler).toHaveBeenCalledWith('state-immediate');
    expect(focusHandler).toHaveBeenCalledWith({
      requestId: 'focus-immediate',
      runId: 'validation-run-history-follow-up-2',
    });
    unregisterState();
    unregisterFocus();
  });

  it('posts the exact validation acknowledgement payload to the native host', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    reportValidationRunFocused({
      requestId: 'request-1',
      rootTaskId: 'validation-run-history-root',
      runId: 'validation-run-history-follow-up-2',
      requestText: 'Produce the final implementation brief with the reviewed evidence.',
      resultText: 'Run 3 is ready for history review.',
      documentPaths: ['/fixtures/documents/preview.py'],
      artifactIds: ['validation-preview'],
      previewArtifactId: null,
      isOverviewOpen: true,
    });

    expect(postMessage).toHaveBeenCalledWith({
      type: 'validationRunFocused',
      requestId: 'request-1',
      rootTaskId: 'validation-run-history-root',
      runId: 'validation-run-history-follow-up-2',
      requestText: 'Produce the final implementation brief with the reviewed evidence.',
      resultText: 'Run 3 is ready for history review.',
      documentPaths: ['/fixtures/documents/preview.py'],
      artifactIds: ['validation-preview'],
      previewArtifactId: null,
      isOverviewOpen: true,
    });
  });
});

describe('result widget resize bridge', () => {
  it('sends the dynamic minimum width only for layout-aware resizes', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    requestResize(636, 400, 'layout', 636);

    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestResize',
      width: 636,
      height: 400,
      resizeIntent: 'layout',
      minimumWidth: 636,
    });
  });
});

describe('agent task artifact preview transport re-exports', () => {
  it('previewFile posts a previewFile message and resolves from the matching onFilePreviewReady callback', async () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    const request = previewFile('/private/reports/report.md');
    const sent = postMessage.mock.calls.find((call) => call[0]?.type === 'previewFile')?.[0];
    expect(sent).toMatchObject({ type: 'previewFile', path: '/private/reports/report.md' });

    window.basilAgentTask?.onFilePreviewReady({
      requestId: sent.requestId,
      path: '/private/reports/report.md',
      name: 'report.md',
      kind: 'markdown',
      content: '# Report',
    });

    await expect(request).resolves.toMatchObject({ kind: 'markdown', content: '# Report' });
  });

  it('clearFilePreview posts a clearFilePreview message with the given request ID', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    clearFilePreview('preview-1');

    expect(postMessage).toHaveBeenCalledWith({ type: 'clearFilePreview', requestId: 'preview-1' });
  });
});

describe('local web preview bridge payloads', () => {
  it('builds an explicit static-mode payload from a percent-encoded file URL, carrying rootTaskId and the raw canonical path', () => {
    expect(buildStaticLocalWebPreview('/private/reports/design #1?.html', 'task-1', 'artifact-1', 'root-1')).toEqual({
      mode: 'static',
      targetUrl: 'file:///private/reports/design%20%231%3F.html',
      artifactId: 'artifact-1',
      agentTaskId: 'task-1',
      rootTaskId: 'root-1',
      canonicalPath: '/private/reports/design #1?.html',
      displayName: 'design #1?.html',
    });
  });

  it('builds an explicit devServer-mode payload for the same HTML path, proving mode is never inferred from extension', () => {
    expect(buildLocalServerPreview('/private/reports/design #1?.html', 'task-1', 'artifact-1', 'root-1')).toEqual({
      mode: 'devServer',
      targetUrl: 'file:///private/reports/design%20%231%3F.html',
      artifactId: 'artifact-1',
      agentTaskId: 'task-1',
      rootTaskId: 'root-1',
      canonicalPath: '/private/reports/design #1?.html',
      displayName: 'design #1?.html',
    });
  });
});

describe('file preview window bridge context', () => {
  it('passes agentTaskId and rootTaskId through to the native host when provided', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    openFilePreviewWindow('/private/reports/report.md', { agentTaskId: 'task-1', rootTaskId: 'root-1' });

    expect(postMessage).toHaveBeenCalledWith({
      type: 'openFilePreviewWindow',
      path: '/private/reports/report.md',
      agentTaskId: 'task-1',
      rootTaskId: 'root-1',
    });
  });

  it('omits context fields as undefined when the caller supplies none, preserving today\'s call sites', () => {
    const postMessage = vi.fn();
    window.webkit = {
      messageHandlers: {
        agentTaskBridge: { postMessage },
      },
    };

    openFilePreviewWindow('/private/reports/report.md');

    expect(postMessage).toHaveBeenCalledWith({
      type: 'openFilePreviewWindow',
      path: '/private/reports/report.md',
      agentTaskId: undefined,
      rootTaskId: undefined,
    });
  });
});
