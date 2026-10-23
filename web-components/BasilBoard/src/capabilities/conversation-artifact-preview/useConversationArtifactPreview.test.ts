import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useConversationArtifactPreview } from './useConversationArtifactPreview';

const bridgeMocks = vi.hoisted(() => ({
  createBoardArtifactPreviewTransport: vi.fn(() => ({
    previewFile: vi.fn(),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn().mockReturnValue(() => {}),
    setInlineNativePreviewFrame: vi.fn(),
    hideInlineNativePreview: vi.fn(),
    clearInlineNativePreview: vi.fn(),
  })),
}));
vi.mock('../../services/artifactPreviewBridge', () => bridgeMocks);

describe('useConversationArtifactPreview', () => {
  beforeEach(() => {
    bridgeMocks.createBoardArtifactPreviewTransport.mockClear();
  });

  it('starts with no selection and a stable transport across re-renders', () => {
    const { result, rerender } = renderHook(
      (props) => useConversationArtifactPreview(props),
      { initialProps: { selectedConversationId: 'conv-1' } },
    );

    expect(result.current.selection).toBeUndefined();
    const firstTransport = result.current.transport;
    rerender({ selectedConversationId: 'conv-1' });
    expect(result.current.transport).toBe(firstTransport);
    expect(bridgeMocks.createBoardArtifactPreviewTransport).toHaveBeenCalledTimes(1);
  });

  it('onPreviewArtifact selects the given artifact for the active conversation', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: 'conv-1' }));

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });

    expect(result.current.selection).toEqual({ conversationId: 'conv-1', agentTaskId: 'task-1', artifactId: 'artifact-1' });
  });

  it('onPreviewArtifact is a no-op without an active conversation', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: undefined }));

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });

    expect(result.current.selection).toBeUndefined();
  });

  it('rejects blank task and artifact IDs and preserves an equivalent selection', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: 'conv-1' }));

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });
    const selection = result.current.selection;

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });
    expect(result.current.selection).toBe(selection);

    act(() => {
      result.current.onPreviewArtifact('', 'artifact-2');
    });
    expect(result.current.selection).toBe(selection);
  });

  it('onViewAllArtifacts selects the task without a specific artifact', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: 'conv-1' }));

    act(() => {
      result.current.onViewAllArtifacts('task-1');
    });

    expect(result.current.selection).toEqual({ conversationId: 'conv-1', agentTaskId: 'task-1', artifactId: undefined });
  });

  it('onSelectArtifact updates only the artifactId of an existing selection', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: 'conv-1' }));

    act(() => {
      result.current.onViewAllArtifacts('task-1');
    });
    act(() => {
      result.current.onSelectArtifact('artifact-2');
    });

    expect(result.current.selection).toEqual({ conversationId: 'conv-1', agentTaskId: 'task-1', artifactId: 'artifact-2' });
  });

  it('onCloseSidebar clears the selection', () => {
    const { result } = renderHook(() => useConversationArtifactPreview({ selectedConversationId: 'conv-1' }));

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });
    act(() => {
      result.current.onCloseSidebar();
    });

    expect(result.current.selection).toBeUndefined();
  });

  it('clears an existing selection when the active conversation changes', () => {
    const { result, rerender } = renderHook(
      (props) => useConversationArtifactPreview(props),
      { initialProps: { selectedConversationId: 'conv-1' } },
    );

    act(() => {
      result.current.onPreviewArtifact('task-1', 'artifact-1');
    });
    expect(result.current.selection).toBeDefined();

    rerender({ selectedConversationId: 'conv-2' });
    expect(result.current.selection).toBeUndefined();
  });
});
