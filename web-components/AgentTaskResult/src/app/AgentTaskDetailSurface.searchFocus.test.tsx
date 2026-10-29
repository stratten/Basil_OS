// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import type { SearchFocus } from '@shared/search/searchFocusStore';
import { clearSearchFocus, publishSearchFocus } from '@shared/search/searchFocusStore';
import { AgentTaskDetailSurface } from './AgentTaskDetailSurface';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const { resultContentProps } = vi.hoisted(() => ({
  resultContentProps: [] as Array<{
    navigationRequest?: { nonce: number; runId: string; target: { kind: string }; flash?: boolean } | null;
    suppressOpenAtLatest?: boolean;
    searchFocus?: SearchFocus | null;
  }>,
}));

vi.mock('../components/ResultContent', () => ({
  default: (props: (typeof resultContentProps)[number]) => {
    resultContentProps.push(props);
    return null;
  },
}));
vi.mock('../components/TextFollowUp', () => ({ default: () => null }));
vi.mock('../services/bridge', () => ({
  checkFilePreviewAvailability: vi.fn((paths: string[]) => Promise.resolve(new Set(paths))),
  reportValidationRunFocused: vi.fn(),
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
  openContainingFolder: vi.fn(),
  openFilePreviewWindow: vi.fn(),
  registerFilesPickedHandler: vi.fn(() => () => {}),
  registerFilePreviewUpdateHandler: vi.fn(() => () => {}),
  pickFiles: vi.fn(),
}));

function turn(id: string) {
  return {
    id,
    agentTaskText: `Question ${id}`,
    result: `Answer ${id}`,
    status: 'completed',
    files: [],
    reference_paths: [],
    timestamp: '2026-09-24T12:00:00.000Z',
  };
}

const chain = {
  agentTaskId: 'turn-3',
  rootTaskId: 'root',
  originalPrompt: 'Question turn-3',
  status: 'completed',
  result: 'Answer turn-3',
  structuredFiles: [],
  referencePaths: [],
  currentTurnTaskId: 'turn-3',
  agentTaskHistory: [turn('root'), turn('turn-2')],
  progressSteps: [],
  executionTimeline: [],
  stepDetails: [],
  showWorkflowPlan: false,
  isStreaming: false,
  checkpointAvailable: false,
  thinkingSegments: [],
  delegatedProviderReportCards: [],
} as unknown as DisplayableAgentTask;

function surface(source: DisplayableAgentTask) {
  return (
    <AgentTaskDetailSurface
      displaySource={source}
      selectedAgent={null}
      detailTrayOpen={false}
      detailTrayWidth={320}
      onDetailTrayWidthChange={() => {}}
      onDetailTrayModeChange={() => {}}
      selectedDetail={undefined}
      selectedDetailId={null}
      selectedDetailOwnerId={null}
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
      onOpenDetailTray={() => {}}
      onCloseDetailTray={() => {}}
      onJumpToLatestDetail={() => {}}
    />
  );
}

const lastProps = () => resultContentProps[resultContentProps.length - 1];

describe('AgentTaskDetailSurface search focus', () => {
  beforeEach(() => {
    resultContentProps.length = 0;
    clearSearchFocus();
  });
  afterEach(() => clearSearchFocus());

  function mount(source: DisplayableAgentTask) {
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => { root.render(surface(source)); });
    return { root, unmount: () => act(() => { root.unmount(); }) };
  }

  it('jumps to the first matched turn once and hands the focus to the content', () => {
    publishSearchFocus({ scopeId: 'root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['missing', 'turn-2', 'root'] });
    const view = mount(chain);
    try {
      expect(lastProps().navigationRequest).toEqual(expect.objectContaining({ runId: 'turn-2', target: { kind: 'run' }, flash: false }));
      expect(lastProps().suppressOpenAtLatest).toBe(true);
      expect(lastProps().searchFocus?.tokens).toEqual(['lisbon']);

      const firstNonce = lastProps().navigationRequest!.nonce;
      act(() => { view.root.render(surface({ ...chain })); });
      expect(lastProps().navigationRequest!.nonce).toBe(firstNonce);
    } finally {
      view.unmount();
    }
  });

  it('jumps again when the same chain is chosen again from the results', () => {
    publishSearchFocus({ scopeId: 'root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['turn-2'] });
    const view = mount(chain);
    try {
      const firstNonce = lastProps().navigationRequest!.nonce;
      act(() => { publishSearchFocus({ scopeId: 'root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['root'] }); });
      expect(lastProps().navigationRequest!.nonce).toBeGreaterThan(firstNonce);
      expect(lastProps().navigationRequest!.runId).toBe('root');
    } finally {
      view.unmount();
    }
  });

  it('can jump to the latest turn', () => {
    publishSearchFocus({ scopeId: 'root', query: 'q', tokens: ['question'], matchedIds: ['turn-3'] });
    const view = mount(chain);
    try {
      expect(lastProps().navigationRequest?.runId).toBe('turn-3');
    } finally {
      view.unmount();
    }
  });

  it('ignores a focus for a different chain, or one whose turns are not in this chain', () => {
    publishSearchFocus({ scopeId: 'other-root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['turn-2'] });
    const view = mount(chain);
    try {
      expect(lastProps().navigationRequest).toBeNull();
      expect(lastProps().suppressOpenAtLatest).toBe(false);
      expect(lastProps().searchFocus).toBeNull();
      act(() => { publishSearchFocus({ scopeId: 'root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['gone'] }); });
      expect(lastProps().navigationRequest).toBeNull();
      expect(lastProps().suppressOpenAtLatest).toBe(false);
    } finally {
      view.unmount();
    }
  });

  it('stops suppressing the open-at-latest scroll once the focus is cleared', () => {
    publishSearchFocus({ scopeId: 'root', query: 'lisbon', tokens: ['lisbon'], matchedIds: ['turn-2'] });
    const view = mount(chain);
    try {
      act(() => { clearSearchFocus(); });
      expect(lastProps().searchFocus).toBeNull();
      expect(lastProps().suppressOpenAtLatest).toBe(false);
    } finally {
      view.unmount();
    }
  });
});
