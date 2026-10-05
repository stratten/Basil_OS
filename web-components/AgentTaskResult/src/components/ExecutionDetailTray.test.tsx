// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { InitMessage, StepDetailEntry, TimelineEntry } from '../types';
import ExecutionDetailTray from './ExecutionDetailTray';
import { deriveAgentRunPresentation } from './run/agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './run/agentTaskRunFocus';
import * as bridge from '../services/bridge';
import {
  DETAIL_TRAY_MIN_WIDTH,
} from '../app/detailTraySizing';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const artifact = {
  artifactId: 'artifact-report',
  displayName: 'résumé-東京.md',
  localPath: '/private/reports/résumé-東京.md',
  artifactKind: 'file' as const,
  operation: 'create',
  lifecycle: 'verified' as const,
  preview: { capability: 'unknown' as const },
  verification: { status: 'verified' as const, summary: 'Receipt matched' },
  sourceStepId: 'step-write',
};

const artifacts = {
  all: [{ ...artifact, group: 'produced' as const }],
  produced: [{ ...artifact, group: 'produced' as const }],
  retrieved: [],
  ungrouped: [],
};

const runs: AgentTaskRunFocusSummary[] = [
  {
    id: 'task-1',
    kind: 'root',
    ordinal: 1,
    label: 'Initial request',
    requestText: 'Create the report',
    resultText: 'Created the report.',
    timestamp: '2026-08-09T20:00:00Z',
    taskStatus: 'completed',
    isProcessing: false,
    documentCount: 1,
    structuredFiles: [],
    executionTimeline: [],
  },
];

function detail(overrides: Partial<StepDetailEntry> = {}): StepDetailEntry {
  return {
    id: 'detail-report',
    timestamp: '2026-08-09T20:00:00Z',
    content: 'Created report.md',
    detail_kind: 'artifact',
    summary: 'Created report.md',
    body: '{"private":"must-not-render"}',
    metadata: { artifact: { private_path: '/private/reports/résumé-東京.md' } },
    artifact,
    ...overrides,
  };
}

function tray(overrides: Partial<React.ComponentProps<typeof ExecutionDetailTray>> = {}) {
  return (
    <ExecutionDetailTray
      detail={detail()}
      isOpen
      presencePhase="present"
      onPresenceTransitionEnd={() => {}}
      trayWidth={320}
      onTrayWidthChange={() => {}}
      followLatest
      hasNewerDetail={false}
      onClose={() => {}}
      onJumpToLatest={() => {}}
      artifacts={artifacts}
      timeline={[]}
      isProcessing={false}
      terminalStatus="completed"
      agentTaskId="task-1"
      rootTaskId="root-1"
      isPreviewArtifactFileAvailable
      onPreviewArtifact={() => {}}
      onClosePreview={() => {}}
      onCloseRunPanel={() => {}}
      runs={runs}
      focusedRunId="task-1"
      currentRunId="task-1"
      locationRunId="task-1"
      peekedRunIds={[]}
      onNavigateRun={() => {}}
      onTogglePeekRun={() => {}}
      onOpenRunDocuments={() => {}}
      onJumpToLatestRun={() => {}}
      {...overrides}
    />
  );
}

describe('ExecutionDetailTray artifact detail', () => {
  it('retains the tray shell in an exiting presence phase without exposing it to assistive technology', () => {
    const markup = renderToStaticMarkup(tray({ presencePhase: 'exiting' }));

    expect(markup).toContain('data-presence-phase="exiting"');
    expect(markup).toContain('aria-hidden="true"');
  });

  it('renders a selected artifact name and preview action without implementation metadata', () => {
    const markup = renderToStaticMarkup(tray());

    for (const text of ['résumé-東京.md', 'Preview résumé-東京.md']) {
      expect(markup).toContain(text);
    }
    for (const text of ['Operation', 'Lifecycle', 'Verification', 'create', 'Receipt matched', 'step-write']) {
      expect(markup).not.toContain(text);
    }
    expect(markup).not.toContain('/private/reports/résumé-東京.md');
    expect(markup).not.toContain('must-not-render');
    expect(markup).not.toContain('private_path');
  });

  it('routes a produced-group preview artifact through the tab strip instead of the bare inline preview', () => {
    const markup = renderToStaticMarkup(tray({ previewArtifact: artifacts.produced[0] }));

    expect(markup).toContain('artifact-review-workspace');
    expect(markup).toContain('artifact-review-tab');
    expect(markup).toContain('résumé-東京.md');
  });

  it('renders unavailable state without a navigation control for a historical artifact', () => {
    const markup = renderToStaticMarkup(tray({
      detail: detail({ artifact: { ...artifact, lifecycle: 'unavailable', localPath: undefined } }),
    }));

    expect(markup).toContain('Artifact unavailable');
    expect(markup).not.toContain('View in artifact dock');
  });

  it('invokes the preview route with the typed artifact ID', () => {
    const onPreviewArtifact = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(tray({ onPreviewArtifact }));
      });
      const button = Array.from(container.querySelectorAll('button')).find(value => value.textContent === 'Preview résumé-東京.md');
      act(() => {
        button?.click();
      });
      expect(onPreviewArtifact).toHaveBeenCalledWith('artifact-report');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('exposes no browser preview action for a Markdown tray preview', () => {
    const openFile = vi.spyOn(bridge, 'openFile');
    const openContainingFolder = vi.spyOn(bridge, 'openContainingFolder');
    const openFilePreviewWindow = vi.spyOn(bridge, 'openFilePreviewWindow');
    const openLocalWebPreview = vi.spyOn(bridge, 'openLocalWebPreview');
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(tray({ previewArtifact: artifacts.produced[0] }));
      });
      const openFileButton = container.querySelector<HTMLButtonElement>('[aria-label="Open File"]');
      const openFolderButton = container.querySelector<HTMLButtonElement>('[aria-label="Show in Folder"]');
      const openPreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Open Preview Window"]');
      const openStaticPreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Preview static page"]');
      const openServerPreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Preview with local server"]');
      const closePreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Close preview"]');
      const collapsePanelButton = container.querySelector<HTMLButtonElement>('[aria-label="Collapse run panel"]');

      act(() => {
        openFileButton?.click();
        openFolderButton?.click();
        openPreviewButton?.click();
      });

      expect(openFileButton?.getAttribute('title')).toBe('Open File');
      expect(openFolderButton?.getAttribute('title')).toBe('Show in Folder');
      expect(openPreviewButton?.getAttribute('title')).toBe('Open Preview Window');
      expect(openStaticPreviewButton).toBeNull();
      expect(openServerPreviewButton).toBeNull();
      expect(closePreviewButton?.getAttribute('title')).toBe('Close preview');
      expect(closePreviewButton?.querySelector('.tray-artifact-preview-symbol')).not.toBeNull();
      expect(collapsePanelButton?.querySelector('.tray-artifact-preview-symbol')).not.toBeNull();
      expect(openFile).toHaveBeenCalledWith('/private/reports/résumé-東京.md');
      expect(openContainingFolder).toHaveBeenCalledWith('/private/reports/résumé-東京.md');
      expect(openFilePreviewWindow).toHaveBeenCalledWith('/private/reports/résumé-東京.md', { agentTaskId: 'task-1', rootTaskId: 'root-1' });
      expect(openLocalWebPreview).not.toHaveBeenCalled();
    } finally {
      openFile.mockRestore();
      openContainingFolder.mockRestore();
      openFilePreviewWindow.mockRestore();
      openLocalWebPreview.mockRestore();
      window.basilAgentTask?.onInit({} as InitMessage);
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('exposes both explicit preview actions for an HTML tray preview and sends the chosen mode', () => {
    const openLocalWebPreview = vi.spyOn(bridge, 'openLocalWebPreview');
    const htmlArtifact = {
      ...artifact,
      artifactId: 'artifact-html',
      displayName: 'index.html',
      localPath: '/private/reports/index.html',
      group: 'produced' as const,
    };
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(tray({
          previewArtifact: htmlArtifact,
          artifacts: { all: [htmlArtifact], produced: [htmlArtifact], retrieved: [], ungrouped: [] },
        }));
      });
      const openStaticPreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Preview static page"]');
      const openServerPreviewButton = container.querySelector<HTMLButtonElement>('[aria-label="Preview with local server"]');

      act(() => {
        openStaticPreviewButton?.click();
      });
      expect(openLocalWebPreview).toHaveBeenCalledWith({
        mode: 'static',
        targetUrl: 'file:///private/reports/index.html',
        artifactId: 'artifact-html',
        agentTaskId: 'task-1',
        rootTaskId: 'root-1',
        canonicalPath: '/private/reports/index.html',
        displayName: 'index.html',
      });

      act(() => {
        openServerPreviewButton?.click();
      });
      expect(openLocalWebPreview).toHaveBeenCalledWith({
        mode: 'devServer',
        targetUrl: 'file:///private/reports/index.html',
        artifactId: 'artifact-html',
        agentTaskId: 'task-1',
        rootTaskId: 'root-1',
        canonicalPath: '/private/reports/index.html',
        displayName: 'index.html',
      });
    } finally {
      openLocalWebPreview.mockRestore();
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('exposes neither preview action for an unavailable artifact', () => {
    const unavailable = {
      ...artifact,
      lifecycle: 'unavailable' as const,
      localPath: undefined,
      group: 'produced' as const,
    };
    const markup = renderToStaticMarkup(tray({
      previewArtifact: unavailable,
      artifacts: { all: [unavailable], produced: [unavailable], retrieved: [], ungrouped: [] },
    }));

    expect(markup).not.toContain('Preview static page');
    expect(markup).not.toContain('Preview with local server');
  });

  it('keeps non-artifact detail metadata and markdown rendering unchanged', () => {
    const markup = renderToStaticMarkup(tray({
      detail: detail({
        detail_kind: 'tool_result',
        artifact: undefined,
        body: 'Completed safely.',
        metadata: { tool_name: 'shell_service.execute_command' },
      }),
    }));

    expect(markup).toContain('tool name');
    expect(markup).toContain('shell_service.execute_command');
    expect(markup).toContain('Completed safely.');
    expect(markup).not.toContain('Preview résumé-東京.md');
  });

  it('resizes the drawer through its keyboard separator within bounds', () => {
    const onTrayWidthChange = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(tray({ detail: undefined, onTrayWidthChange }));
      });
      const separator = container.querySelector<HTMLDivElement>('[role="separator"]');
      expect(separator).not.toBeNull();

      act(() => {
        separator?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowLeft' }));
        separator?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Home' }));
      });

      expect(onTrayWidthChange).toHaveBeenNthCalledWith(1, 336);
      expect(onTrayWidthChange).toHaveBeenNthCalledWith(2, DETAIL_TRAY_MIN_WIDTH);
      expect(separator?.getAttribute('aria-valuemax')).toBeNull();
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('requires a deliberate horizontal drag before resizing the drawer', () => {
    const onTrayWidthChange = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const dispatchPointer = (target: HTMLDivElement, type: string, clientX: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        button: { value: 0 },
        clientX: { value: clientX },
        isPrimary: { value: true },
        pointerId: { value: 1 },
      });
      target.dispatchEvent(event);
    };

    try {
      act(() => {
        root.render(tray({ detail: undefined, onTrayWidthChange }));
      });
      const separator = container.querySelector<HTMLDivElement>('[role="separator"]');
      expect(separator).not.toBeNull();
      Object.assign(separator!, {
        hasPointerCapture: () => true,
        releasePointerCapture: vi.fn(),
        setPointerCapture: vi.fn(),
      });

      act(() => {
        dispatchPointer(separator!, 'pointerdown', 100);
        dispatchPointer(separator!, 'pointermove', 103);
      });
      expect(onTrayWidthChange).not.toHaveBeenCalled();
      expect(container.querySelector('.execution-detail-tray')?.classList.contains('execution-detail-tray--resizing')).toBe(false);

      act(() => {
        dispatchPointer(separator!, 'pointermove', 104);
        dispatchPointer(separator!, 'pointerup', 104);
      });
      expect(onTrayWidthChange).toHaveBeenCalledWith(316);
      expect(container.querySelector('.execution-detail-tray')?.classList.contains('execution-detail-tray--resizing')).toBe(false);
      expect(separator?.releasePointerCapture).toHaveBeenCalledWith(1);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('signals resizing to the host at pointerdown, before any drag-activation distance is covered', () => {
    // A native window resize that was already queued (e.g. from opening the
    // tray or switching to this preview moments earlier) can fire in the
    // gap between pointerdown and the drag-activation threshold, corrupting
    // the OS mouse-tracking loop before any perceptible drag distance is
    // covered. The host-facing signal must therefore engage at pointerdown
    // itself, not wait for `execution-detail-tray--resizing` to apply.
    const onResizingChange = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const dispatchPointer = (target: HTMLDivElement, type: string, clientX: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        button: { value: 0 },
        clientX: { value: clientX },
        isPrimary: { value: true },
        pointerId: { value: 1 },
      });
      target.dispatchEvent(event);
    };

    try {
      act(() => {
        root.render(tray({ detail: undefined, onResizingChange }));
      });
      const separator = container.querySelector<HTMLDivElement>('[role="separator"]');
      expect(separator).not.toBeNull();
      Object.assign(separator!, {
        hasPointerCapture: () => true,
        releasePointerCapture: vi.fn(),
        setPointerCapture: vi.fn(),
      });

      act(() => {
        dispatchPointer(separator!, 'pointerdown', 100);
      });
      expect(onResizingChange).toHaveBeenCalledWith(true);
      expect(onResizingChange).toHaveBeenCalledTimes(1);

      act(() => {
        dispatchPointer(separator!, 'pointerup', 100);
      });
      expect(onResizingChange).toHaveBeenLastCalledWith(false);
      expect(onResizingChange).toHaveBeenCalledTimes(2);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('renders an evidence-first run card with high-level phases and produced documents', () => {
    const timeline: TimelineEntry[] = [
      { type: 'step', timestamp: '2026-08-09T19:00:00Z', content: 'Done', detail_kind: 'final_summary', summary: 'Delivered report' },
      { type: 'step', timestamp: '2026-08-09T20:00:01Z', content: 'researching', metadata: { progress_phase: 'Researching', progress_status: 'completed' } },
      { type: 'tool_start', timestamp: '2026-08-09T20:00:02Z', content: 'Search sources', detail_kind: 'tool_input', correlation_id: 'search-1', summary: 'Search sources' },
      { type: 'tool_complete', timestamp: '2026-08-09T20:00:03Z', content: 'Found sources', detail_kind: 'tool_result', correlation_id: 'search-1', summary: 'Found sources' },
      { type: 'artifact', timestamp: '2026-08-09T20:00:04Z', content: 'Created report', detail_kind: 'artifact', artifact },
    ];
    const markup = renderToStaticMarkup(tray({ detail: undefined, timeline }));

    for (const text of ['Run overview', 'Ready for review', 'Completing task', '1 document', 'résumé-東京.md', 'Delivered report']) {
      expect(markup).toContain(text);
    }
    expect(markup.indexOf('Completing task')).toBeLessThan(markup.indexOf('Delivered report'));
    expect(markup.indexOf('run-card-stage--outcome')).toBeLessThan(markup.indexOf('Ready for review'));
    expect(markup).not.toContain('run-card-status');
    expect((markup.match(/>Run overview</g) || [])).toHaveLength(1);
    expect(markup).toContain('aria-label="Preview résumé-東京.md"');
    expect(markup).not.toContain('Search sources');
  });

  it('shows a version-count badge in the run card file list for a multi-revision produced document', () => {
    const multiRevisionArtifact = {
      ...artifact,
      review: { revision: 3, revisionCount: 3, kind: 'markdown' as const, snapshotStatus: 'available' as const },
    };
    const multiRevisionArtifacts = {
      all: [{ ...multiRevisionArtifact, group: 'produced' as const }],
      produced: [{ ...multiRevisionArtifact, group: 'produced' as const }],
      retrieved: [],
      ungrouped: [],
    };
    const markup = renderToStaticMarkup(tray({
      detail: undefined,
      artifacts: multiRevisionArtifacts,
      timeline: [
        { type: 'artifact', timestamp: '2026-08-09T20:00:04Z', content: 'Created report', detail_kind: 'artifact', artifact: multiRevisionArtifact },
      ],
    }));

    expect(markup).toContain('run-card-artifact-badge');
    expect(markup).toContain('>v3<');
  });

  it('omits the version-count badge in the run card file list for a single-revision produced document', () => {
    const markup = renderToStaticMarkup(tray({
      detail: undefined,
      timeline: [
        { type: 'artifact', timestamp: '2026-08-09T20:00:04Z', content: 'Created report', detail_kind: 'artifact', artifact },
      ],
    }));

    expect(markup).toContain('aria-label="Preview résumé-東京.md"');
    expect(markup).not.toContain('run-card-artifact-badge');
  });

  it('renders every turn in the task map and expands only the location turn', () => {
    const onNavigateRun = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const chainRuns: AgentTaskRunFocusSummary[] = [
      ...runs,
      {
        id: 'follow-up-1',
        kind: 'follow_up',
        ordinal: 2,
        label: 'Follow-up 1',
        requestText: 'Add the requested comparison',
        resultText: 'Added the requested comparison.',
        timestamp: '2026-08-09T20:02:00Z',
        taskStatus: 'completed',
        isProcessing: false,
        documentCount: 0,
        structuredFiles: [],
        executionTimeline: [],
      },
    ];

    try {
      act(() => {
        root.render(tray({
          detail: undefined,
          runs: chainRuns,
          focusedRunId: 'follow-up-1',
          currentRunId: 'follow-up-1',
          locationRunId: 'follow-up-1',
          onNavigateRun,
        }));
      });
      expect(container.querySelector('nav.agent-run-map')).not.toBeNull();
      expect(container.querySelector('.agent-run-history-tray')).toBeNull();
      expect(container.querySelectorAll('section.run-card')).toHaveLength(1);
      const followUpTurn = Array.from(container.querySelectorAll('.agent-run-map-turn'))
        .find(turn => turn.querySelector('.agent-run-map-label')?.textContent === 'Follow-up 1');
      expect(followUpTurn?.querySelector('section.run-card')).not.toBeNull();
      expect(followUpTurn?.querySelector('.run-card-artifacts')?.textContent).toContain('résumé-東京.md');

      const initialRun = Array.from(container.querySelectorAll<HTMLButtonElement>('.agent-run-map-turn-link'))
        .find(button => button.textContent?.includes('Initial request'));
      act(() => {
        initialRun?.click();
      });

      expect(onNavigateRun).toHaveBeenCalledWith('task-1', { kind: 'run' });
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('navigates from a single-run overview stage without rendering the task map', () => {
    const onNavigateRun = vi.fn();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const timeline: TimelineEntry[] = [
      { type: 'step', timestamp: '2026-08-09T20:00:01Z', content: 'researching', metadata: { progress_phase: 'Researching', progress_status: 'completed' } },
    ];

    try {
      act(() => {
        root.render(tray({ detail: undefined, timeline, onNavigateRun }));
      });
      expect(container.querySelector('.agent-run-map')).toBeNull();
      const phaseStage = container.querySelector<HTMLButtonElement>('button.run-card-stage--phase');
      expect(phaseStage?.textContent).toContain('Completing task');
      act(() => {
        phaseStage?.click();
      });
      expect(onNavigateRun).toHaveBeenCalledWith('task-1', { kind: 'section', section: 'activity' });

      act(() => {
        container.querySelector<HTMLButtonElement>('button.run-card-stage--outcome')?.click();
      });
      expect(onNavigateRun).toHaveBeenLastCalledWith('task-1', { kind: 'section', section: 'result' });
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('keeps raw tool activity out of the high-level terminal overview', () => {
    const presentation = deriveAgentRunPresentation([
      { type: 'step', timestamp: '2026-08-09T20:00:01Z', content: 'Routing', metadata: { progress_phase: 'Routing', progress_status: 'completed' } },
      { type: 'tool_start', timestamp: '2026-08-09T20:00:02Z', content: 'Search sources', detail_kind: 'tool_input', correlation_id: 'search-1' },
    ], 'completed', false);
    const markup = renderToStaticMarkup(tray({ detail: undefined, runPresentation: presentation }));

    expect(presentation.stages).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'phase', state: 'completed' }),
      expect.objectContaining({ kind: 'tool', state: 'recorded' }),
    ]));
    expect(markup).toContain('run-card-stage--phase is-completed');
    expect(markup).not.toContain('run-card-stage--tool');
  });

  it('ignores planning notes and preserves durable source order for equal timestamps', () => {
    const presentation = deriveAgentRunPresentation([
      { type: 'step', timestamp: '2026-08-09T20:00:00Z', content: 'planning note one', detail_kind: 'step_note', summary: 'planning note one' },
      { type: 'step', timestamp: '2026-08-09T20:00:01Z', content: 'First phase', metadata: { progress_phase: 'First phase' } },
      { type: 'step', timestamp: '2026-08-09T20:00:01Z', content: 'Second phase', metadata: { progress_phase: 'Second phase' } },
      { type: 'step', timestamp: 'not-a-date', content: 'Third phase', metadata: { progress_phase: 'Third phase' } },
    ], 'processing', true);

    expect(presentation.stages.map(stage => stage.label)).toEqual(['First phase', 'Second phase', 'Third phase']);
    expect(presentation.stages.map(stage => stage.label)).not.toContain('planning note one');
  });
});
