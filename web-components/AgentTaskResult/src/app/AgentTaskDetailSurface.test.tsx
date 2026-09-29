// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask, StepDetailEntry, ValidationRunFocusRequest } from '../types';
import { AgentTaskDetailSurface } from './AgentTaskDetailSurface';
import { checkFilePreviewAvailability, reportValidationRunFocused } from '../services/bridge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
  openContainingFolder: vi.fn(),
  openFilePreviewWindow: vi.fn(),
  buildInlineStaticPreviewUrl: vi.fn((path: string) => `basil-inline-preview://local${path}`),
  checkFilePreviewAvailability: vi.fn((paths: string[]) => Promise.resolve(new Set(paths))),
  reportValidationRunFocused: vi.fn(),
  previewFile: vi.fn(() => Promise.resolve({
    requestId: 'preview-report',
    path: '/tmp/report.md',
    name: 'report.md',
    kind: 'markdown',
    content: '# Report',
  })),
  clearFilePreview: vi.fn(),
  agentTaskArtifactPreviewTransport: {
    previewFile: vi.fn(() => Promise.resolve({
      requestId: 'preview-report',
      path: '/tmp/report.md',
      name: 'report.md',
      kind: 'markdown',
      content: '# Report',
    })),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn(() => () => {}),
    setInlineNativePreviewFrame: vi.fn(),
    hideInlineNativePreview: vi.fn(),
    clearInlineNativePreview: vi.fn(),
  },
  registerFilesPickedHandler: vi.fn(() => () => {}),
  registerFilePreviewUpdateHandler: vi.fn(() => () => {}),
  pickFiles: vi.fn(),
}));
vi.mock('../components/TextFollowUp', () => ({
  default: () => null,
}));

const artifact = {
  artifact_id: 'artifact-report',
  display_name: 'report.md',
  local_path: '/tmp/report.md',
  artifact_kind: 'file' as const,
  operation: 'create',
  lifecycle: 'ready' as const,
  preview: { capability: 'unknown' as const },
  verification: { status: 'unknown' as const },
};

const displaySource: DisplayableAgentTask = {
  agentTaskId: 'task-report',
  originalPrompt: 'Create report',
  status: 'completed',
  result: 'Created report.',
  delegatedProviderReportCards: [],
  structuredFiles: [{ name: 'report.md', path: '/tmp/report.md', operation: 'create', artifact }],
  referencePaths: [],
  agentTaskHistory: [],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [],
};

const selectedDetail: StepDetailEntry = {
  id: 'detail-report',
  timestamp: '2026-08-09T20:00:00Z',
  content: 'Created report.md',
  detail_kind: 'artifact',
  summary: 'Created report.md',
  body: 'Created report.md',
  metadata: { artifact },
  artifact: {
    artifactId: 'artifact-report',
    displayName: 'report.md',
    localPath: '/tmp/report.md',
    artifactKind: 'file',
    operation: 'create',
    lifecycle: 'ready',
    preview: { capability: 'unknown' },
    verification: { status: 'unknown' },
  },
};

function surface(
  ownerId: string | null,
  detail: StepDetailEntry | undefined,
  detailTrayOpen = true,
  onOpenDetailTray = () => {},
  onDetailTrayModeChange = () => {},
  source = displaySource,
  validationRunRequest: ValidationRunFocusRequest | null = null,
) {
  return (
    <AgentTaskDetailSurface
      displaySource={source}
      selectedAgent={null}
      detailTrayOpen={detailTrayOpen}
      detailTrayWidth={320}
      onDetailTrayWidthChange={() => {}}
      onDetailTrayModeChange={onDetailTrayModeChange}
      selectedDetail={detail}
      selectedDetailId={detail?.id || null}
      selectedDetailOwnerId={ownerId}
      followLatestDetail={false}
      hasNewerDetail={false}
      textFollowUpMode={false}
      isProcessing={false}
      captureState={null}
      onRetry={() => {}}
      onContinue={() => {}}
      onSelectDetail={() => {}}
      onCancelTextFollowUp={() => {}}
      onStartVoiceFollowUp={() => {}}
      onOpenDetailTray={onOpenDetailTray}
      onCloseDetailTray={() => {}}
      onJumpToLatestDetail={() => {}}
      validationRunRequest={validationRunRequest}
    />
  );
}

async function flushPreviewAvailability() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AgentTaskDetailSurface artifact route', () => {
  it('renders a collapsed run rail until the overview is explicitly opened', () => {
    const markup = document.createElement('div');
    const root = createRoot(markup);

    try {
      act(() => {
        root.render(surface(null, undefined, false));
      });
      expect(markup.querySelector('.execution-detail-tray--run-panel')).toBeNull();
      expect(markup.querySelector('button.agent-run-rail-toggle')).not.toBeNull();
      expect(markup.querySelector('button.agent-run-rail-toggle')?.getAttribute('aria-label')).toContain('Expand completed run overview');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('recomputes the run rail when the mutable store record resolves in place', () => {
    const mutableSource: DisplayableAgentTask = {
      ...displaySource,
      status: 'failed',
      outcome: 'partial',
    };
    const markup = document.createElement('div');
    const root = createRoot(markup);

    try {
      act(() => {
        root.render(surface(null, undefined, false, undefined, undefined, mutableSource));
      });
      expect(markup.querySelector('.agent-run-rail-stage-tooltip')?.textContent).toBe('Partial result: completed');

      mutableSource.status = 'completed';
      mutableSource.outcome = 'success';
      act(() => {
        root.render(surface(null, undefined, false, undefined, undefined, mutableSource));
      });

      expect(markup.querySelector('.agent-run-rail-stage-tooltip')?.textContent).toBe('Run completed: completed');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('keeps the rail available for an empty follow-up when an earlier run has context', () => {
    const onOpenDetailTray = vi.fn();
    const followUpSource: DisplayableAgentTask = {
      ...displaySource,
      agentTaskId: 'follow-up-task',
      status: 'processing',
      result: '',
      structuredFiles: [],
      agentTaskHistory: [{
        id: 'root-task',
        agentTaskText: 'Create report',
        result: 'Created report.md.',
        files: [{ name: 'report.md', path: '/tmp/report.md', operation: 'create' }],
        reference_paths: [],
        timestamp: '2026-08-10T12:00:00Z',
      }],
    };
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface(null, undefined, false, onOpenDetailTray, () => {}, followUpSource));
      });
      const control = container.querySelector<HTMLButtonElement>('button.agent-run-rail-toggle');

      expect(control).not.toBeNull();
      act(() => {
        control?.click();
      });
      expect(onOpenDetailTray).toHaveBeenCalledWith('overview');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('opens a preview for an explicitly selected artifact', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface('task-report', selectedDetail));
      });
      await flushPreviewAvailability();
      expect(container.textContent).toContain('report.md');
      expect(container.querySelector('[aria-label="Close preview"]')).not.toBeNull();
      expect(container.textContent).not.toContain('Operation');
      expect(container.textContent).not.toContain('Lifecycle');
      expect(container.textContent).not.toContain('Verification');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('opens a document from the run overview in preview mode', async () => {
    const onOpenDetailTray = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface(null, undefined, true, onOpenDetailTray));
      });
      await flushPreviewAvailability();
      const preview = container.querySelector<HTMLButtonElement>('button.run-card-artifact');
      act(() => {
        preview?.click();
      });
      expect(onOpenDetailTray).toHaveBeenCalledWith('preview');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('renders a compact reopen rail only after the run card closes', () => {
    const onOpenDetailTray = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface(null, undefined, false, onOpenDetailTray));
      });
      const control = container.querySelector<HTMLButtonElement>('button.agent-run-rail-toggle');
      act(() => {
        control?.click();
      });
      expect(onOpenDetailTray).toHaveBeenCalledWith('overview');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('returns to the run overview when the preview closes', async () => {
    const onDetailTrayModeChange = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface('task-report', selectedDetail, true, () => {}, onDetailTrayModeChange));
      });
      await flushPreviewAvailability();
      const closePreview = container.querySelector<HTMLButtonElement>('[aria-label="Close preview"]');
      act(() => {
        closePreview?.click();
      });
      expect(container.querySelector('.detail-tray-title')?.textContent).toBe('Run overview');
      expect(container.querySelector('button.run-card-artifact')).not.toBeNull();
      expect(onDetailTrayModeChange).toHaveBeenCalledWith('overview');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('changes the run overview documents when a historical run is focused', async () => {
    const historicalSource: DisplayableAgentTask = {
      ...displaySource,
      agentTaskId: 'follow-up-task',
      timestamp: '2026-08-10T12:01:00Z',
      structuredFiles: [{ name: 'follow-up.md', path: '/tmp/follow-up.md', operation: 'create' }],
      agentTaskHistory: [{
        id: 'root-task',
        agentTaskText: 'Investigate the integration workflow',
        result: 'Created initial.md.',
        files: [{ name: 'initial.md', path: '/tmp/initial.md', operation: 'create' }],
        reference_paths: [],
        timestamp: '2026-08-10T12:00:00Z',
      }],
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, historicalSource));
      });
      await flushPreviewAvailability();
      expect(container.querySelector('.run-card-artifacts')?.textContent).toContain('follow-up.md');
      expect(container.querySelector('.run-card-artifacts')?.textContent).not.toContain('initial.md');

      const historyToggle = container.querySelector<HTMLButtonElement>('.agent-run-history-toggle');
      act(() => {
        historyToggle?.click();
      });
      const initialRun = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'))
        .find(button => button.textContent?.includes('Initial request'));
      act(() => {
        initialRun?.click();
      });
      await flushPreviewAvailability();

      expect(initialRun?.getAttribute('aria-pressed')).toBe('true');
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/initial.md']);
      expect(container.querySelector('.run-card-artifacts')?.textContent).toContain('initial.md');
      expect(container.querySelector('.run-card-artifacts')?.textContent).not.toContain('follow-up.md');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('isolates all three runs and restores the newest run after remount', async () => {
    const threeRunSource: DisplayableAgentTask = {
      ...displaySource,
      agentTaskId: 'newest-task',
      originalPrompt: 'Produce the final implementation brief',
      timestamp: '2026-08-10T12:02:00Z',
      structuredFiles: [{ name: 'newest.md', path: '/tmp/newest.md', operation: 'create' }],
      agentTaskHistory: [
        {
          id: 'root-task',
          agentTaskText: 'Inspect the integration workflow',
          result: 'Root run ready.',
          files: [{ name: 'root.md', path: '/tmp/root.md', operation: 'create' }],
          reference_paths: [],
          timestamp: '2026-08-10T12:00:00Z',
        },
        {
          id: 'middle-task',
          agentTaskText: 'Add the deployment constraints',
          result: 'Middle run ready.',
          files: [{ name: 'middle.md', path: '/tmp/middle.md', operation: 'create' }],
          reference_paths: [],
          timestamp: '2026-08-10T12:01:00Z',
        },
      ],
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    let root = createRoot(container);

    const expectFocusedArtifacts = (expectedName: string, absentNames: string[]) => {
      const artifactText = container.querySelector('.run-card-artifacts')?.textContent;
      expect(artifactText).toContain(expectedName);
      absentNames.forEach(name => expect(artifactText).not.toContain(name));
    };

    try {
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, threeRunSource));
      });
      await flushPreviewAvailability();
      expectFocusedArtifacts('newest.md', ['root.md', 'middle.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/newest.md']);

      act(() => {
        container.querySelector<HTMLButtonElement>('.agent-run-history-toggle')?.click();
      });
      const historyRows = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-history-row'));
      const rootRun = historyRows.find(button => button.textContent?.includes('Initial request'));
      const middleRun = historyRows.find(button => button.textContent?.includes('Follow-up 1'));
      const newestRun = historyRows.find(button => button.textContent?.includes('Follow-up 2'));

      expect(rootRun?.getAttribute('aria-label')).toContain('Inspect the integration workflow');
      expect(middleRun?.getAttribute('aria-label')).toContain('Add the deployment constraints');
      expect(newestRun?.getAttribute('aria-label')).toContain('Produce the final implementation brief');

      act(() => {
        rootRun?.click();
      });
      await flushPreviewAvailability();
      expect(rootRun?.getAttribute('aria-pressed')).toBe('true');
      expectFocusedArtifacts('root.md', ['middle.md', 'newest.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/root.md']);

      act(() => {
        middleRun?.click();
      });
      await flushPreviewAvailability();
      expect(middleRun?.getAttribute('aria-pressed')).toBe('true');
      expectFocusedArtifacts('middle.md', ['root.md', 'newest.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/middle.md']);

      act(() => {
        newestRun?.click();
      });
      await flushPreviewAvailability();
      expect(newestRun?.getAttribute('aria-pressed')).toBe('true');
      expectFocusedArtifacts('newest.md', ['root.md', 'middle.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/newest.md']);

      act(() => {
        root.unmount();
      });
      root = createRoot(container);
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, threeRunSource));
      });
      await flushPreviewAvailability();
      expectFocusedArtifacts('newest.md', ['root.md', 'middle.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/newest.md']);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('acknowledges the initial newest run and each validation-requested run with isolated fixture identity', async () => {
    const validationSource: DisplayableAgentTask = {
      ...displaySource,
      agentTaskId: 'validation-run-history-follow-up-2',
      rootTaskId: 'validation-run-history-root',
      originalPrompt: 'Produce the final implementation brief with the reviewed evidence.',
      result: 'Run 3 is ready for history review.',
      structuredFiles: [{
        name: 'preview.py',
        path: '/fixtures/documents/preview.py',
        operation: 'create',
        artifact: { ...artifact, artifact_id: 'validation-preview', display_name: 'preview.py', local_path: '/fixtures/documents/preview.py' },
      }],
      agentTaskHistory: [
        {
          id: 'validation-run-history-root',
          agentTaskText: 'Review the initial implementation evidence.',
          result: 'Run 1 is ready for history review.',
          files: [{
            name: 'run-summary.md',
            path: '/fixtures/documents/run-summary.md',
            operation: 'create',
            artifact: { ...artifact, artifact_id: 'validation-run-summary', display_name: 'run-summary.md', local_path: '/fixtures/documents/run-summary.md' },
          }],
          reference_paths: [],
          timestamp: '2026-08-18T12:00:00Z',
        },
        {
          id: 'validation-run-history-follow-up-1',
          agentTaskText: 'Incorporate the review notes before finalizing.',
          result: 'Run 2 is ready for history review.',
          files: [{
            name: 'notes.txt',
            path: '/fixtures/documents/notes.txt',
            operation: 'create',
            artifact: { ...artifact, artifact_id: 'validation-notes', display_name: 'notes.txt', local_path: '/fixtures/documents/notes.txt' },
          }],
          reference_paths: [],
          timestamp: '2026-08-18T12:01:00Z',
        },
      ],
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const renderRequest = (request: ValidationRunFocusRequest) => {
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, validationSource, request));
      });
    };

    try {
      vi.mocked(reportValidationRunFocused).mockClear();
      renderRequest({ requestId: 'initial-state' });
      await flushPreviewAvailability();
      expect(reportValidationRunFocused).toHaveBeenLastCalledWith(expect.objectContaining({
        requestId: 'initial-state',
        runId: 'validation-run-history-follow-up-2',
        requestText: 'Produce the final implementation brief with the reviewed evidence.',
        resultText: 'Run 3 is ready for history review.',
        documentPaths: ['/fixtures/documents/preview.py'],
        artifactIds: ['validation-preview'],
        isOverviewOpen: true,
      }));

      const expectedRuns = [
        ['focus-root', 'validation-run-history-root', 'Review the initial implementation evidence.', 'Run 1 is ready for history review.', '/fixtures/documents/run-summary.md', 'validation-run-summary'],
        ['focus-middle', 'validation-run-history-follow-up-1', 'Incorporate the review notes before finalizing.', 'Run 2 is ready for history review.', '/fixtures/documents/notes.txt', 'validation-notes'],
        ['focus-newest', 'validation-run-history-follow-up-2', 'Produce the final implementation brief with the reviewed evidence.', 'Run 3 is ready for history review.', '/fixtures/documents/preview.py', 'validation-preview'],
      ] as const;
      for (const [requestId, runId, requestText, resultText, documentPath, artifactId] of expectedRuns) {
        renderRequest({ requestId, runId });
        await flushPreviewAvailability();
        expect(reportValidationRunFocused).toHaveBeenLastCalledWith(expect.objectContaining({
          requestId,
          runId,
          requestText,
          resultText,
          documentPaths: [documentPath],
          artifactIds: [artifactId],
          isOverviewOpen: true,
        }));
      }

      act(() => {
        root.unmount();
      });
      const remountedRoot = createRoot(container);
      act(() => {
        remountedRoot.render(surface(null, undefined, true, () => {}, () => {}, validationSource, { requestId: 'remount-state' }));
      });
      await flushPreviewAvailability();
      expect(reportValidationRunFocused).toHaveBeenLastCalledWith(expect.objectContaining({
        requestId: 'remount-state',
        runId: 'validation-run-history-follow-up-2',
      }));
      act(() => {
        remountedRoot.unmount();
      });
    } finally {
      container.remove();
    }
  });
});
