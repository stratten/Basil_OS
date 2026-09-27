import { beforeEach, describe, expect, it, vi } from 'vitest';

const initPayload = {
  apiBaseUrl: 'http://127.0.0.1:9000',
  theme: {
    backgroundPrimary: '#ffffff',
    primary: '#003087',
    secondary: '#33559b',
    textPrimary: '#001a3d',
  },
  fonts: {
    fontFamily: 'Basil',
    fontFamilyMedium: 'Basil Medium',
    fontFamilyBold: 'Basil Bold',
  },
};

describe('bridge initialization queue', () => {
  beforeEach(() => {
    vi.resetModules();
    window.basilBoardBridge = undefined;
  });

  it('delivers a native init queued before the standalone app registers', async () => {
    const bridge = await import('./bridge');
    const onInit = vi.fn();

    bridge.enqueueInit(initPayload);
    bridge.registerBridgeHandlers({
      onInit,
      onVoiceCaptureState: vi.fn(),
      onVoiceCaptureFinished: vi.fn(),
      onStatusIconChanged: vi.fn(),
    });

    expect(onInit).toHaveBeenCalledTimes(1);
    expect(onInit).toHaveBeenCalledWith(initPayload);
  });

  it('queues valid Board Conversation availability, rejects malformed state, and delivers later updates', async () => {
    const bridge = await import('./bridge');
    const handler = vi.fn();

    bridge.enqueueBoardConversationAvailabilityChanged({ availability: 'unavailable' });
    bridge.enqueueBoardConversationAvailabilityChanged({ availability: 'invalid' as never });
    bridge.registerBoardConversationAvailabilityHandler(handler);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith({ availability: 'unavailable' });

    window.basilBoardBridge?.onBoardConversationAvailabilityChanged?.({ availability: 'available' });

    expect(handler).toHaveBeenCalledTimes(2);
    expect(handler).toHaveBeenLastCalledWith({ availability: 'available' });
  });

  it('queues a native To-Do workspace file selection until its composer registers', async () => {
    const bridge = await import('./bridge');
    const handler = vi.fn();

    bridge.registerBridgeHandlers({
      onInit: vi.fn(),
      onVoiceCaptureState: vi.fn(),
      onVoiceCaptureFinished: vi.fn(),
      onStatusIconChanged: vi.fn(),
    });
    window.basilBoardBridge?.onTodoWorkspaceFilesPicked?.({ paths: ['/tmp/action-items.pdf'] });
    bridge.registerTodoWorkspaceFilesPickedHandler(handler);

    expect(handler).toHaveBeenCalledWith(['/tmp/action-items.pdf']);
  });

  it('queues a native To-Do reference selection until the detail pane registers', async () => {
    const bridge = await import('./bridge');
    const handler = vi.fn();

    bridge.registerBridgeHandlers({
      onInit: vi.fn(),
      onVoiceCaptureState: vi.fn(),
      onVoiceCaptureFinished: vi.fn(),
      onStatusIconChanged: vi.fn(),
    });
    window.basilBoardBridge?.onTodoReferenceFilesPicked?.({ paths: ['/tmp/brief.pdf'] });
    bridge.registerTodoReferenceFilesPickedHandler(handler);

    expect(handler).toHaveBeenCalledWith(['/tmp/brief.pdf']);
  });

  it('delivers only the latest valid queued Agent Task origin navigation, including conversations', async () => {
    const bridge = await import('./bridge');
    const handler = vi.fn();

    bridge.enqueueAgentTaskOriginNavigation({ originType: 'todo', originId: 'todo-1' });
    bridge.enqueueAgentTaskOriginNavigation({ originType: 'unknown' as never, originId: 'ignored' });
    bridge.enqueueAgentTaskOriginNavigation({ originType: 'conversation', originId: 'conversation-2' });
    bridge.registerAgentTaskOriginNavigationHandler(handler);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith({ originType: 'conversation', originId: 'conversation-2' });
  });
});

describe('pickWorkspaceDirectory', () => {
  beforeEach(() => {
    vi.resetModules();
    window.basilBoardBridge = undefined;
    window.webkit = {
      messageHandlers: {
        basilBoardBridge: { postMessage: vi.fn() },
      },
    };
  });

  function capturedRequestId(): string {
    const postMessage = window.webkit!.messageHandlers.basilBoardBridge!.postMessage as ReturnType<typeof vi.fn>;
    const lastCall = postMessage.mock.calls[postMessage.mock.calls.length - 1][0] as { requestId: string };
    return lastCall.requestId;
  }

  it('resolves with the selected canonical path', async () => {
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();
    const requestId = capturedRequestId();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({
      requestId,
      status: 'selected',
      path: '/Users/example/Projects/basil',
    });

    await expect(pending).resolves.toEqual({ status: 'selected', path: '/Users/example/Projects/basil' });
  });

  it('retains the picker callback after the application registers bridge handlers', async () => {
    const bridge = await import('./bridge');
    bridge.registerBridgeHandlers({
      onInit: vi.fn(),
      onVoiceCaptureState: vi.fn(),
      onVoiceCaptureFinished: vi.fn(),
      onStatusIconChanged: vi.fn(),
    });
    const pending = bridge.pickWorkspaceDirectory();
    const requestId = capturedRequestId();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({
      requestId,
      status: 'selected',
      path: '/Users/example/Projects/basil',
    });

    await expect(pending).resolves.toEqual({ status: 'selected', path: '/Users/example/Projects/basil' });
  });

  it('resolves with cancelled and no path when the user cancels the picker', async () => {
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();
    const requestId = capturedRequestId();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({ requestId, status: 'cancelled' });

    await expect(pending).resolves.toEqual({ status: 'cancelled' });
  });

  it('resolves with the Swift-supplied error message for an unavailable path', async () => {
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();
    const requestId = capturedRequestId();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({
      requestId,
      status: 'error',
      message: 'The selected folder no longer exists.',
    });

    await expect(pending).resolves.toEqual({
      status: 'error',
      message: 'The selected folder no longer exists.',
    });
  });

  it('resolves with a generic error for a malformed selected payload missing a path', async () => {
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();
    const requestId = capturedRequestId();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({ requestId, status: 'selected' } as never);

    await expect(pending).resolves.toEqual({
      status: 'error',
      message: 'The workspace directory could not be used.',
    });
  });

  it('ignores a response for an unrelated requestId and leaves the original request pending', async () => {
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();

    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({ requestId: 'not-a-real-request', status: 'cancelled' });

    const requestId = capturedRequestId();
    window.basilBoardBridge!.onWorkspaceDirectoryPicked!({ requestId, status: 'cancelled' });

    await expect(pending).resolves.toEqual({ status: 'cancelled' });
  });

  it('resolves with an error immediately when the native bridge is unavailable', async () => {
    window.webkit = undefined;
    const bridge = await import('./bridge');

    await expect(bridge.pickWorkspaceDirectory()).resolves.toEqual({
      status: 'error',
      message: 'Native bridge is unavailable.',
    });
  });

  it('resolves with a timeout error if Swift never responds', async () => {
    vi.useFakeTimers();
    const bridge = await import('./bridge');
    const pending = bridge.pickWorkspaceDirectory();

    await vi.advanceTimersByTimeAsync(120000);

    await expect(pending).resolves.toEqual({
      status: 'error',
      message: 'Workspace directory picker timed out.',
    });
    vi.useRealTimers();
  });
});
