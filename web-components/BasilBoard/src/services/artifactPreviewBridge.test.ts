import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  checkConversationArtifactPreviewAvailability,
  createBoardArtifactPreviewTransport,
  openConversationArtifactContainingFolder,
  openConversationArtifactFile,
  openConversationArtifactPreviewWindow,
  openConversationLocalServerPreview,
  openConversationStaticLocalWebPreview,
} from './artifactPreviewBridge';

function armBridge() {
  const postMessage = vi.fn();
  window.webkit = { messageHandlers: { basilBoardBridge: { postMessage } } };
  return postMessage;
}

beforeEach(() => {
  window.webkit = undefined;
});

afterEach(() => {
  window.webkit = undefined;
});

describe('artifactPreviewBridge', () => {
  it('openConversationArtifactFile posts an openFile message with the given path', () => {
    const postMessage = armBridge();
    openConversationArtifactFile('/tmp/report.md');
    expect(postMessage).toHaveBeenCalledWith({ type: 'openFile', path: '/tmp/report.md' });
  });

  it('openConversationArtifactContainingFolder posts an openContainingFolder message', () => {
    const postMessage = armBridge();
    openConversationArtifactContainingFolder('/tmp/report.md');
    expect(postMessage).toHaveBeenCalledWith({ type: 'openContainingFolder', path: '/tmp/report.md' });
  });

  it('openConversationArtifactPreviewWindow posts an openFilePreviewWindow message', () => {
    const postMessage = armBridge();
    openConversationArtifactPreviewWindow('/tmp/report.md');
    expect(postMessage).toHaveBeenCalledWith({ type: 'openFilePreviewWindow', path: '/tmp/report.md' });
  });

  it('openConversationStaticLocalWebPreview posts an explicit static-mode message', () => {
    const postMessage = armBridge();
    openConversationStaticLocalWebPreview('/tmp/index.html', 'task-1', 'artifact-1');
    expect(postMessage).toHaveBeenCalledWith({
      type: 'openLocalWebPreview',
      mode: 'static',
      targetUrl: 'file:///tmp/index.html',
      artifactId: 'artifact-1',
      agentTaskId: 'task-1',
      displayName: 'index.html',
    });
  });

  it('openConversationLocalServerPreview posts an explicit devServer-mode message for the same HTML path', () => {
    const postMessage = armBridge();
    openConversationLocalServerPreview('/tmp/index.html', 'task-2', 'artifact-2');
    expect(postMessage).toHaveBeenCalledWith({
      type: 'openLocalWebPreview',
      mode: 'devServer',
      targetUrl: 'file:///tmp/index.html',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'index.html',
    });
  });

  it('encodes reserved characters in local preview file URLs', () => {
    const postMessage = armBridge();
    openConversationStaticLocalWebPreview('/tmp/design #1?.html', 'task-3', 'artifact-3');

    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      targetUrl: 'file:///tmp/design%20%231%3F.html',
    }));
  });

  it('checkConversationArtifactPreviewAvailability resolves with the confirmed paths from the native callback', async () => {
    const postMessage = armBridge();
    const request = checkConversationArtifactPreviewAvailability(['/tmp/a.md', '/tmp/a.md', '/tmp/b.md']);
    const sent = postMessage.mock.calls[0]?.[0];
    expect(sent).toMatchObject({ type: 'checkFilePreviewAvailability', paths: ['/tmp/a.md', '/tmp/b.md'] });

    window.basilBoardBridge?.onFilePreviewAvailability?.({ requestId: sent.requestId, availablePaths: ['/tmp/a.md'] });

    await expect(request).resolves.toEqual(new Set(['/tmp/a.md']));
  });

  it('checkConversationArtifactPreviewAvailability assumes every path is available when the native bridge is absent', async () => {
    await expect(checkConversationArtifactPreviewAvailability(['/tmp/a.md'])).resolves.toEqual(new Set(['/tmp/a.md']));
  });

  it('createBoardArtifactPreviewTransport.previewFile posts previewFile without a duplicated type field and resolves from onFilePreviewReady', async () => {
    const postMessage = armBridge();
    const transport = createBoardArtifactPreviewTransport();
    const promise = transport.previewFile('/tmp/report.md');
    const sent = postMessage.mock.calls[0]?.[0];
    expect(sent).toEqual({ type: 'previewFile', requestId: sent.requestId, path: '/tmp/report.md' });

    window.basilBoardBridge?.onFilePreviewReady?.({
      requestId: sent.requestId,
      path: '/tmp/report.md',
      name: 'report.md',
      kind: 'markdown',
      content: '# Report',
    });

    await expect(promise).resolves.toMatchObject({ kind: 'markdown', content: '# Report' });
  });
});
