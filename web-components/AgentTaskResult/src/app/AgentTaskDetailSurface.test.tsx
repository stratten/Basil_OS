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
      expect(markup.querySelector('.agent-run-rail-flow-stage[data-tooltip]')?.getAttribute('data-tooltip')).toBe('Partial result: completed');

      mutableSource.status = 'completed';
      mutableSource.outcome = 'success';
      act(() => {
        root.render(surface(null, undefined, false, undefined, undefined, mutableSource));
      });

      expect(markup.querySelector('.agent-run-rail-flow-stage[data-tooltip]')?.getAttribute('data-tooltip')).toBe('Run completed: completed');
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

      const initialRun = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-map-turn-link'))
        .find(button => button.textContent?.includes('Initial request'));
      act(() => {
        initialRun?.click();
      });
      await flushPreviewAvailability();

      expect(initialRun?.getAttribute('aria-current')).toBe('location');
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

  it('opens a turn’s only document from its document count in the run map', async () => {
    const onDetailTrayModeChange = vi.fn();
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
        root.render(surface(null, undefined, true, () => {}, onDetailTrayModeChange, historicalSource));
      });
      await flushPreviewAvailability();
      const chip = container.querySelector<HTMLButtonElement>('.agent-run-map-documents');
      expect(chip?.textContent).toBe('1 doc');
      expect(chip?.getAttribute('aria-label')).toBe('Open 1 doc from Initial request');

      act(() => {
        chip?.click();
      });
      await flushPreviewAvailability();

      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/initial.md']);
      expect(onDetailTrayModeChange).toHaveBeenLastCalledWith('preview');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('moves the run-map focus with scrolling while the tray shows the overview without a selected detail', async () => {
    const historicalSource: DisplayableAgentTask = {
      ...displaySource,
      agentTaskId: 'follow-up-task',
      timestamp: '2026-08-10T12:01:00Z',
      structuredFiles: [],
      agentTaskHistory: [{
        id: 'root-task',
        agentTaskText: 'Investigate the integration workflow',
        result: 'Investigated.',
        files: [],
        reference_paths: [],
        timestamp: '2026-08-10T12:00:00Z',
      }],
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const mockTop = (element: Element, top: number) => {
      (element as HTMLElement).getBoundingClientRect = () => ({ top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    };
    const expandedTurnLabels = () => Array.from(container.querySelectorAll('.agent-run-map-turn.is-expanded .agent-run-map-label'))
      .map(label => label.textContent);

    try {
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, historicalSource));
      });
      await flushPreviewAvailability();
      expect(expandedTurnLabels()).toEqual(['Follow-up 1']);

      const main = container.querySelector<HTMLElement>('.main-content');
      if (!main) throw new Error('Expected the main content scroller.');
      Object.defineProperty(main, 'clientHeight', { configurable: true, value: 400 });
      Object.defineProperty(main, 'scrollHeight', { configurable: true, value: 2000 });
      Object.defineProperty(main, 'scrollTop', { configurable: true, writable: true, value: 0 });
      mockTop(main, 0);
      Array.from(container.querySelectorAll('[data-run-anchor]')).forEach((anchor, index) => mockTop(anchor, index * 100));
      act(() => {
        main.dispatchEvent(new Event('scroll'));
      });

      expect(container.querySelector('.agent-run-map-turn.is-location .agent-run-map-label')?.textContent).toBe('Initial request');
      expect(expandedTurnLabels()).toEqual(['Initial request']);
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

      const historyRows = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-map-turn-link'));
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
      expect(rootRun?.getAttribute('aria-current')).toBe('location');
      expectFocusedArtifacts('root.md', ['middle.md', 'newest.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/root.md']);

      act(() => {
        middleRun?.click();
      });
      await flushPreviewAvailability();
      expect(middleRun?.getAttribute('aria-current')).toBe('location');
      expectFocusedArtifacts('middle.md', ['root.md', 'newest.md']);
      expect(checkFilePreviewAvailability).toHaveBeenLastCalledWith(['/tmp/middle.md']);

      act(() => {
        newestRun?.click();
      });
      await flushPreviewAvailability();
      expect(newestRun?.getAttribute('aria-current')).toBe('location');
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

describe('AgentTaskDetailSurface turn labels', () => {
  const chainSource: DisplayableAgentTask = {
    ...displaySource,
    currentTurnTaskId: 'follow-up-task',
    agentTaskHistory: [{
      id: 'root-task',
      agentTaskText: 'Create report',
      result: 'Created report.md.',
      files: [],
      reference_paths: [],
      timestamp: '2026-08-10T12:00:00Z',
    }],
  };

  it('opens the run overview when a turn label is clicked', () => {
    const onOpenDetailTray = vi.fn();
    const onDetailTrayModeChange = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(surface(null, undefined, false, onOpenDetailTray, onDetailTrayModeChange, chainSource));
      });
      const rootLabel = Array.from(container.querySelectorAll<HTMLButtonElement>('button.turn-label--interactive'))
        .find(button => button.textContent?.includes('Initial request'));

      expect(rootLabel).toBeDefined();
      act(() => {
        rootLabel?.click();
      });
      expect(onDetailTrayModeChange).toHaveBeenCalledWith('overview');
      expect(onOpenDetailTray).toHaveBeenCalledWith('overview');
    } finally {
      act(() => {
        root.unmount();
      });
    }
  });

  it('marks the focused turn only while the run overview is open', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const pressed = () => Array.from(
      container.querySelectorAll<HTMLButtonElement>('button.turn-label--interactive[aria-pressed="true"]'),
    ).map(button => button.textContent);

    try {
      act(() => {
        root.render(surface(null, undefined, false, () => {}, () => {}, chainSource));
      });
      expect(pressed()).toEqual([]);

      const rootLabel = Array.from(container.querySelectorAll<HTMLButtonElement>('button.turn-label--interactive'))
        .find(button => button.textContent?.includes('Initial request'));
      act(() => {
        rootLabel?.click();
      });
      act(() => {
        root.render(surface(null, undefined, true, () => {}, () => {}, chainSource));
      });
      await flushPreviewAvailability();

      expect(pressed()).toHaveLength(1);
      expect(pressed()[0]).toContain('Initial request');

      act(() => {
        root.render(surface(null, undefined, false, () => {}, () => {}, chainSource));
      });
      expect(pressed()).toEqual([]);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});

describe('AgentTaskDetailSurface run controls', () => {
  function renderStatus(status: string) {
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => {
      root.render(surface(null, undefined, false, () => {}, () => {}, { ...displaySource, status, result: '' }));
    });
    return { container, unmount: () => act(() => root.unmount()) };
  }

  it('offers the regular rich note box with an icon Pause while the run is working', () => {
    const { container, unmount } = renderStatus('processing');
    try {
      const composer = container.querySelector('.run-control-composer');
      expect(composer?.getAttribute('data-run-control-mode')).toBe('running');
      expect(composer?.querySelector('[role="textbox"][aria-label="Note for Basil"]')).not.toBeNull();
      expect(composer?.querySelector('.rich-text-composer-toolbar')).not.toBeNull();
      const pause = composer?.querySelector('button[aria-label="Pause"]');
      expect(pause?.getAttribute('title')).toBe('Pause after the current step');
      expect(pause?.textContent).toBe('');
      expect(pause?.querySelector('svg')).not.toBeNull();
      expect(composer?.querySelector('button[aria-label="Send"]')).not.toBeNull();
      expect(container.querySelector('form[aria-label="Run controls"]')).toBeNull();
    } finally {
      unmount();
    }
  });

  it('offers an icon Resume in the same box while the run is paused', () => {
    const { container, unmount } = renderStatus('paused');
    try {
      const composer = container.querySelector('.run-control-composer');
      expect(composer?.getAttribute('data-run-control-mode')).toBe('paused');
      expect(composer?.querySelector('[role="textbox"][aria-label="Note for when Basil resumes"]')).not.toBeNull();
      const resume = composer?.querySelector('button[aria-label="Resume"]');
      expect(resume?.getAttribute('title')).toBe('Resume (⌘↩)');
      expect(resume?.textContent).toBe('');
      expect(composer?.querySelector('button[aria-label="Pause"]')).toBeNull();
      expect(composer?.querySelector('button[aria-label="Send"]')).toBeNull();
    } finally {
      unmount();
    }
  });

  it('hides the run controls once the run has finished', () => {
    const { container, unmount } = renderStatus('completed');
    try {
      expect(container.querySelector('.run-control-composer')).toBeNull();
    } finally {
      unmount();
    }
  });
});
