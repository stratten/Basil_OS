import { useLayoutEffect, useRef, useState, type ReactNode, type Ref, type TransitionEvent } from 'react';
import type {
  AgentState,
  BubbleMode,
  CaptureStateMessage,
  DisplayableAgentTask,
  StepDetailEntry,
  ValidationRunFocusRequest,
} from '../types';
import Header from '../components/Header';
import Sidebar from '../components/Sidebar';
import ScheduledAgentTaskDetail from '../components/ScheduledAgentTaskDetail';
import { activityStatusSnapshot } from '../components/result/activityPresentation';
import type { MissedRunToast } from './useHostBridge';
import { AgentTaskDetailSurface } from './AgentTaskDetailSurface';
import DetachedTaskPlaceholder from '../components/DetachedTaskPlaceholder';
import { plainMarkdownText } from '../../../shared/plainMarkdownText';

export function SurfaceStack({ surfaceKey, children }: { surfaceKey: string; children: ReactNode }) {
  const previous = useRef({ key: surfaceKey, children });
  const isFirstRender = useRef(true);
  const [outgoing, setOutgoing] = useState<{ key: string; children: ReactNode } | null>(null);
  const [entering, setEntering] = useState(false);

  // Keep the settled snapshot's children current for whichever surface is
  // presently shown, so a later transition away captures up-to-date
  // outgoing content. This is a plain ref write during render (not inside
  // an effect) on purpose: the transition effect below must depend on
  // `surfaceKey` alone. Depending on `children` too (the previous
  // implementation) meant a same-key content update -- e.g. a streaming
  // progress event from a fast local model -- tore the effect down and
  // re-ran it, and React always invokes the prior effect's cleanup first.
  // That cleanup canceled the in-flight `requestAnimationFrame` that was
  // the only thing that ever flipped `entering` back to `false`, and the
  // early-return guard then skipped rescheduling it (the key hadn't
  // changed), permanently stranding the new surface at `opacity: 0`.
  if (previous.current.key === surfaceKey) {
    previous.current.children = children;
  }

  useLayoutEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setOutgoing(previous.current);
    previous.current = { key: surfaceKey, children };
    setEntering(true);
    const frame = requestAnimationFrame(() => setEntering(false));
    return () => cancelAnimationFrame(frame);
    // surfaceKey is the only thing that should start a transition; see the
    // comment above for why `children` must not be a dependency here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfaceKey]);

  // Authoritative, non-time-based fallback: if the browser actually
  // completes the entering layer's opacity transition, that is proof the
  // surface is visible regardless of whether the rAF above ever fired.
  const completeEntrance = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== 'opacity') return;
    setEntering(false);
  };

  return (
    <div className="agent-task-surface-stack">
      {outgoing && (
        <div
          className="agent-task-surface-layer"
          data-presence-phase="exiting"
          aria-hidden="true"
          inert=""
          onTransitionEnd={(event: TransitionEvent<HTMLDivElement>) => {
            if (event.target === event.currentTarget && event.propertyName === 'opacity') setOutgoing(null);
          }}
        >
          {outgoing.children}
        </div>
      )}
      <div
        className="agent-task-surface-layer"
        data-presence-phase={entering ? 'entering' : 'present'}
        onTransitionEnd={completeEntrance}
      >
        {children}
      </div>
    </div>
  );
}

function RetainedMissedRunToasts({ toasts }: { toasts: MissedRunToast[] }) {
  const [retained, setRetained] = useState<Array<MissedRunToast & { phase: 'entering' | 'present' | 'exiting' }>>(
    () => toasts.map(toast => ({ ...toast, phase: 'entering' })),
  );

  useLayoutEffect(() => {
    const incomingIds = new Set(toasts.map(toast => toast.runId));
    setRetained(current => {
      const currentById = new Map(current.map(toast => [toast.runId, toast]));
      const next = toasts.map(toast => ({
        ...toast,
        phase: currentById.get(toast.runId)?.phase === 'exiting' ? 'entering' : currentById.get(toast.runId)?.phase ?? 'entering',
      }));
      current.forEach(toast => {
        if (!incomingIds.has(toast.runId)) next.push({ ...toast, phase: 'exiting' });
      });
      return next;
    });
    const frame = requestAnimationFrame(() => {
      setRetained(current => current.map(toast => toast.phase === 'entering' ? { ...toast, phase: 'present' } : toast));
    });
    return () => cancelAnimationFrame(frame);
  }, [toasts]);

  if (retained.length === 0) return null;
  return (
    <div className="missed-run-toast-stack">
      {retained.map(toast => (
        <div
          key={toast.runId}
          className="missed-run-toast"
          data-presence-phase={toast.phase}
          aria-hidden={toast.phase === 'exiting'}
          onTransitionEnd={event => {
            if (event.target !== event.currentTarget || event.propertyName !== 'opacity') return;
            setRetained(current => current.filter(item => item.runId !== toast.runId || item.phase !== 'exiting'));
          }}
        >
          <div className="missed-run-toast-title">Missed scheduled run</div>
          <div className="missed-run-toast-task">{plainMarkdownText(toast.title)}</div>
          <div className="missed-run-toast-reason">{toast.reason || 'Basil was not running when this run was due.'}</div>
        </div>
      ))}
    </div>
  );
}

interface AgentTaskResultBodyProps {
  rootRef: Ref<HTMLDivElement>;
  embedded: boolean;
  isChromeCollapsed: boolean;
  detachedRootTaskId: string | null;
  displaySourceDetached: boolean;
  detachedDisplayRootId: string | null;
  detachedRootsElsewhere: Set<string>;
  detailTrayOpen: boolean;
  detailTrayWidth: number;
  onDetailTrayWidthChange: (width: number) => void;
  onDetailTrayModeChange: (mode: 'overview' | 'detail' | 'preview') => void;
  onDetailTrayResizingChange?: (isResizing: boolean) => void;
  displaySource: DisplayableAgentTask | null;
  selectedAgent: AgentState | null;
  selectedDetail: StepDetailEntry | undefined;
  selectedDetailId: string | null;
  selectedDetailOwnerId: string | null;
  followLatestDetail: boolean;
  hasNewerDetail: boolean;
  sidebarExpanded: boolean;
  initialized: boolean;
  initiallyProcessing: boolean;
  selectedScheduledAgentTaskId: string | null;
  createScheduledMode: boolean;
  scheduledListVersion: number;
  viewedDetail: DisplayableAgentTask | null;
  pendingAgentTaskSelection: { agentTaskId: string; epoch: number } | null;
  missedRunToasts: MissedRunToast[];
  captureState: CaptureStateMessage | null;
  textFollowUpMode: boolean;
  isProcessing: boolean;
  isCapturing: boolean;
  bubbleMode: BubbleMode;
  isCollapseIconRotated: boolean;
  showCancelStop: boolean;
  onCancelRunningAgent: () => void;
  onToggleChromeCollapsed: () => void;
  onToggleSidebar: () => void;
  onViewHistoricalAgentTask: (detail: DisplayableAgentTask) => void;
  onViewScheduledAgentTask: (scheduledAgentTaskId: string) => void;
  onCreateScheduledAgentTask: () => void;
  onAgentTaskDeleted: (agentTaskId: string) => void;
  onScheduledCreated: (scheduledAgentTaskId: string) => void;
  onScheduledUpdated: () => void;
  onExitCreateMode: () => void;
  onViewAgentTask: (agentTaskId: string) => void;
  onRetry: (modelId?: string) => void;
  onContinue: () => void;
  onSelectDetail: (ownerTaskId: string, detail: StepDetailEntry, isLatest: boolean) => void;
  onCancelTextFollowUp: () => void;
  onStartVoiceFollowUp: () => void;
  onOpenDetailTray: (mode?: 'overview' | 'detail' | 'preview') => void;
  onCloseDetailTray: () => void;
  onJumpToLatestDetail: () => void;
  validationRunRequest?: ValidationRunFocusRequest | null;
  validationManagedHistoryRestoreRequestId?: string | null;
}

export function AgentTaskResultBody({
  rootRef,
  embedded,
  isChromeCollapsed,
  detachedRootTaskId,
  displaySourceDetached,
  detachedDisplayRootId,
  detachedRootsElsewhere,
  detailTrayOpen,
  detailTrayWidth,
  onDetailTrayWidthChange,
  onDetailTrayModeChange,
  onDetailTrayResizingChange,
  displaySource,
  selectedAgent,
  selectedDetail,
  selectedDetailId,
  selectedDetailOwnerId,
  followLatestDetail,
  hasNewerDetail,
  sidebarExpanded,
  initialized,
  initiallyProcessing,
  selectedScheduledAgentTaskId,
  createScheduledMode,
  scheduledListVersion,
  viewedDetail,
  pendingAgentTaskSelection,
  missedRunToasts,
  captureState,
  textFollowUpMode,
  isProcessing,
  isCapturing,
  bubbleMode,
  isCollapseIconRotated,
  showCancelStop,
  onCancelRunningAgent,
  onToggleChromeCollapsed,
  onToggleSidebar,
  onViewHistoricalAgentTask,
  onViewScheduledAgentTask,
  onCreateScheduledAgentTask,
  onAgentTaskDeleted,
  onScheduledCreated,
  onScheduledUpdated,
  onExitCreateMode,
  onViewAgentTask,
  onRetry,
  onContinue,
  onSelectDetail,
  onCancelTextFollowUp,
  onStartVoiceFollowUp,
  onOpenDetailTray,
  onCloseDetailTray,
  onJumpToLatestDetail,
  validationRunRequest,
  validationManagedHistoryRestoreRequestId,
}: AgentTaskResultBodyProps) {
  const isAwaitingInput =
    selectedAgent?.showApprovalPrompt === true ||
    selectedAgent?.showCheckpointPrompt === true ||
    selectedAgent?.status === 'awaitingInput';
  const collapsedActivityStatus = displaySource
    ? activityStatusSnapshot(displaySource.executionTimeline)
    : undefined;
  const surfaceKey = !detachedRootTaskId && (createScheduledMode || selectedScheduledAgentTaskId)
    ? `scheduled:${selectedScheduledAgentTaskId ?? 'create'}`
    : displaySourceDetached && detachedDisplayRootId
      ? `detached:${detachedDisplayRootId}`
      : displaySource
        ? `agent:${displaySource.agentTaskId}`
        : initialized
          ? 'empty'
          : 'connecting';

  return (
    <div className={`basil-webkit-window-frame${embedded ? ' basil-webkit-window-frame--embedded' : ''}`}>
      <div ref={rootRef} className={`widget-root basil-webkit-window-surface${embedded ? ' widget-root--embedded' : ''}${isChromeCollapsed ? ' chrome-collapsed' : ''}`}>
      <div className="agent-task-header-shell">
        <Header
          isProcessing={displaySourceDetached ? false : isProcessing}
          isCapturing={isCapturing}
          bubbleMode={displaySourceDetached ? 'ambient' : bubbleMode}
          baseColor={getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#33559B'}
          accentColor="#FFFFFF"
          showCancelStop={displaySourceDetached ? false : showCancelStop}
          isCanceling={selectedAgent?.isCanceling === true}
          onCancelRunning={onCancelRunningAgent}
          canCollapse={!embedded}
          hideWindowControls={embedded}
          embedded={embedded}
          taskTitle={displaySource?.taskTitle}
          isCollapsed={isCollapseIconRotated}
          onToggleCollapse={onToggleChromeCollapsed}
          collapsedTaskTitle={isChromeCollapsed ? displaySource?.taskTitle : undefined}
          collapsedStatusText={isChromeCollapsed
            ? (displaySourceDetached ? 'Open in a separate window' : collapsedActivityStatus)
            : undefined}
          isAwaitingInput={displaySourceDetached ? false : isAwaitingInput}
        />
      </div>

        <div
          className="widget-body"
          hidden={isChromeCollapsed}
          aria-hidden={isChromeCollapsed}
          inert={isChromeCollapsed ? '' : undefined}
        >
          {!detachedRootTaskId && (
            <Sidebar
              isExpanded={sidebarExpanded}
              canLoadData={initialized}
              onToggle={onToggleSidebar}
              onViewHistoricalAgentTask={onViewHistoricalAgentTask}
              onViewAgentTask={onViewAgentTask}
              onViewScheduledAgentTask={onViewScheduledAgentTask}
              onCreateScheduledAgentTask={onCreateScheduledAgentTask}
              selectedScheduledAgentTaskId={selectedScheduledAgentTaskId}
              scheduledListVersion={scheduledListVersion}
              viewedAgentTaskId={viewedDetail?.agentTaskId}
              viewedRootId={viewedDetail?.rootTaskId}
              onAgentTaskDeleted={onAgentTaskDeleted}
              detachedRootsElsewhere={detachedRootsElsewhere}
            />
          )}

          <SurfaceStack surfaceKey={surfaceKey}>
          {!detachedRootTaskId && (createScheduledMode || selectedScheduledAgentTaskId) ? (
            <div className="content-area">
              <ScheduledAgentTaskDetail
                scheduledAgentTaskId={selectedScheduledAgentTaskId}
                createMode={createScheduledMode}
                onCreated={onScheduledCreated}
                onUpdated={onScheduledUpdated}
                onExitCreateMode={onExitCreateMode}
                onViewAgentTask={onViewAgentTask}
              />
            </div>
          ) : displaySourceDetached && detachedDisplayRootId ? (
            <DetachedTaskPlaceholder
              rootTaskId={detachedDisplayRootId}
              taskTitle={displaySource?.taskTitle}
            />
          ) : displaySource ? (
            <div className="agent-task-pending-surface">
              <div inert={pendingAgentTaskSelection ? '' : undefined}>
                <AgentTaskDetailSurface
                displaySource={displaySource}
                selectedAgent={selectedAgent}
                detailTrayOpen={detailTrayOpen}
                detailTrayWidth={detailTrayWidth}
                onDetailTrayWidthChange={onDetailTrayWidthChange}
                onDetailTrayModeChange={onDetailTrayModeChange}
                onDetailTrayResizingChange={onDetailTrayResizingChange}
                selectedDetail={selectedDetail}
                selectedDetailId={selectedDetailId}
                selectedDetailOwnerId={selectedDetailOwnerId}
                followLatestDetail={followLatestDetail}
                hasNewerDetail={hasNewerDetail}
                textFollowUpMode={textFollowUpMode}
                isProcessing={isProcessing}
                captureState={captureState}
                onRetry={onRetry}
                onContinue={onContinue}
                onSelectDetail={onSelectDetail}
                onCancelTextFollowUp={onCancelTextFollowUp}
                onStartVoiceFollowUp={onStartVoiceFollowUp}
                onOpenDetailTray={onOpenDetailTray}
                onCloseDetailTray={onCloseDetailTray}
                onJumpToLatestDetail={onJumpToLatestDetail}
                validationRunRequest={validationRunRequest}
                validationManagedHistoryRestoreRequestId={validationManagedHistoryRestoreRequestId}
                />
              </div>
              {pendingAgentTaskSelection && (
                <div className="agent-task-selection-loading-overlay" role="status" aria-label={`Loading selected task ${pendingAgentTaskSelection.agentTaskId}`}>
                  <div className="loading-spinner" />
                  <span>Loading task…</span>
                </div>
              )}
            </div>
          ) : (
            <div className="empty-state" style={{ flex: 1 }}>
              {!initialized ? (
                <>
                  <div className="loading-spinner" />
                  <span>Connecting...</span>
                </>
              ) : initiallyProcessing || pendingAgentTaskSelection ? (
                <>
                  <div className="loading-spinner" />
                  <span>{pendingAgentTaskSelection ? 'Loading task…' : 'Processing...'}</span>
                </>
              ) : (
                <>
                  <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="5.5" y="1" width="5" height="8" rx="2.5" />
                    <path d="M3.5 7a4.5 4.5 0 0 0 9 0" />
                    <line x1="8" y1="11.5" x2="8" y2="14" />
                    <line x1="5.5" y1="14" x2="10.5" y2="14" />
                  </svg>
                  <span>No active agent tasks</span>
                </>
              )}
            </div>
          )}
          </SurfaceStack>
        </div>

      {!detachedRootTaskId && <RetainedMissedRunToasts toasts={missedRunToasts} />}
    </div>
    </div>
  );
}

