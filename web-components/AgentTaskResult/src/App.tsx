import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  BubbleMode,
  CaptureStateMessage,
  DetailSelection,
  DisplayableAgentTask,
  StepDetailEntry,
  ValidationRunFocusRequest,
} from './types';
import {
  cancelRunningAgentTask,
  registerEmbeddedFlagHandler,
  registerExpandChromeForTaskCompletionHandler,
  startFollowUpCapture,
} from './services/bridge';
import * as api from './services/api';
import { agentStore, useSelectedAgent } from './store/agentStore';
import { applyProcessingDefaults } from './app/themeBootstrap';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend, isInFlightAgentStatus } from './app/agentHydration';
import { useHostBridge } from './app/useHostBridge';
import type { MissedRunToast } from './app/useHostBridge';
import { useAgentSelection } from './app/useAgentSelection';
import { useAgentStatusReporting } from './app/useAgentStatusReporting';
import { useResultWidgetSizing } from './app/useResultWidgetSizing';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { AgentTaskResultBody } from './app/AgentTaskResultBody';
import { effectiveRootId, isDisplaySourceDetached } from './app/detachedPresentation';
import { beginRunningAgentCancellation } from './app/runningAgentCancellation';
import { deriveRunPhase } from './components/run/runPhase';

// Initialize the processing-bubble CSS variables at module-load time, before
// React renders, so the bubble has its Royal Purple default *before* the
// Swift host pushes its theme payload.
applyProcessingDefaults();

function logDetailTrayDiagnostic(event: string, payload: Record<string, unknown>): void {
  console.log(`[AgentTaskResult][App][${event}] ${JSON.stringify(payload)}`);
}

export default function App() {
  const selectedAgent = useSelectedAgent() ?? null;
  const [viewedDetail, setViewedDetail] = useState<DisplayableAgentTask | null>(null);
  const [pendingAgentTaskSelection, setPendingAgentTaskSelection] = useState<{ agentTaskId: string; epoch: number } | null>(null);
  const [selectedScheduledAgentTaskId, setSelectedScheduledAgentTaskId] = useState<string | null>(null);
  const [createScheduledMode, setCreateScheduledMode] = useState(false);
  // Monotonic counter bumped whenever we mutate the scheduled-agent-task set
  // so Sidebar refreshes without requiring the user to toggle views.
  const [scheduledListVersion, setScheduledListVersion] = useState(0);
  const [missedRunToasts, setMissedRunToasts] = useState<MissedRunToast[]>([]);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [captureState, setCaptureState] = useState<CaptureStateMessage | null>(null);
  const [textFollowUpMode, setTextFollowUpMode] = useState(false);
  const [detachedRootTaskId, setDetachedRootTaskId] = useState<string | null>(null);
  const [detachedRootsElsewhere, setDetachedRootsElsewhere] = useState<Set<string>>(new Set());
  const [initialized, setInitialized] = useState(false);
  const [embedded, setEmbedded] = useState(
    () => document.documentElement.dataset.agentTaskEmbedded === 'true',
  );
  const [initiallyProcessing, setInitiallyProcessing] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<DetailSelection | null>(null);
  const [validationRunRequest, setValidationRunRequest] = useState<ValidationRunFocusRequest | null>(null);
  const [validationManagedHistoryRestoreRequestId, setValidationManagedHistoryRestoreRequestId] = useState<string | null>(null);
  const [followLatestDetail, setFollowLatestDetail] = useState(true);
  const viewedDetailRef = useRef<DisplayableAgentTask | null>(null);
  const previousDetailTrayOpenRef = useRef(false);

  viewedDetailRef.current = viewedDetail;

  const handleValidationRunStateRequest = useCallback((requestId: string) => {
    setValidationRunRequest({ requestId });
  }, []);

  const handleValidationRunFocus = useCallback((request: Required<ValidationRunFocusRequest>) => {
    setValidationRunRequest(request);
  }, []);

  const handleValidationManagedHistoryRestore = useCallback((requestId: string) => {
    setValidationManagedHistoryRestoreRequestId(requestId);
  }, []);

  const displaySource: DisplayableAgentTask | null = selectedAgent ?? viewedDetail ?? null;
  const detailCandidates = displaySource
    ? [
        ...displaySource.agentTaskHistory.flatMap(item =>
          (item.stepDetails || []).map(detail => ({ ownerTaskId: item.id, detail })),
        ),
        ...displaySource.stepDetails.map(detail => ({ ownerTaskId: displaySource.agentTaskId, detail })),
      ]
    : [];
  const selectedCandidate = selectedDetail
    ? detailCandidates.find(candidate =>
      candidate.ownerTaskId === selectedDetail.ownerTaskId &&
      candidate.detail.id === selectedDetail.detailId,
    )
    : undefined;
  const selectedOwnerId = selectedCandidate?.ownerTaskId || null;
  const latestForOwner = selectedOwnerId
    ? [...detailCandidates].reverse().find(candidate => candidate.ownerTaskId === selectedOwnerId)
    : undefined;
  const selectedDetailEntry = selectedCandidate?.detail;
  const hasNewerDetail = Boolean(
    selectedDetailEntry &&
    latestForOwner &&
    selectedDetailEntry.id !== latestForOwner.detail.id
  );

  useHostBridge({
    setSidebarExpanded,
    setCaptureState,
    setInitialized,
    setInitiallyProcessing,
    setViewedDetail,
    setSelectedScheduledAgentTaskId,
    setCreateScheduledMode,
    setMissedRunToasts,
    setDetachedRootTaskId,
    setDetachedRootsElsewhere,
    viewedDetailRef,
    onValidationRunStateRequest: handleValidationRunStateRequest,
    onValidationRunFocus: handleValidationRunFocus,
    onValidationManagedHistoryRestore: handleValidationManagedHistoryRestore,
  });

  useEffect(() => {
    registerEmbeddedFlagHandler(setEmbedded);
  }, []);

  const {
    handleViewHistoricalAgentTask,
    handleAgentTaskDeleted,
    handleViewScheduledAgentTask,
    handleViewAgentTask,
    handleCreateScheduledAgentTask,
  } = useAgentSelection({
    setViewedDetail,
    setSelectedScheduledAgentTaskId,
    setCreateScheduledMode,
    setScheduledListVersion,
    setPendingAgentTaskSelection,
    selectedAgent,
    viewedDetail,
  });

  const {
    rootRef,
    detailTrayWidth,
    detailTrayOpen,
    openDetailTray,
    setDetailTrayMode,
    setDetailTrayOpen,
    setDetailTrayWidth,
    isChromeCollapsed,
    isCollapseIconRotated,
    handleToggleChromeCollapsed,
    expandChrome,
    setTrayResizing,
  } = useResultWidgetSizing({
    displaySource,
    selectedAgent,
    viewedDetail,
    sidebarExpanded,
    embedded,
    contentSurfaceMode: createScheduledMode || selectedScheduledAgentTaskId
      ? 'scheduled'
      : displaySource
        ? 'agent'
        : 'empty',
    contentSurfaceId: selectedScheduledAgentTaskId ?? displaySource?.agentTaskId ?? null,
    textFollowUpMode,
    isCapturing: captureState?.isCapturing ?? false,
    initialized,
    initiallyProcessing,
  });

  useCollapseShortcut(handleToggleChromeCollapsed, !embedded);

  useEffect(() => {
    registerExpandChromeForTaskCompletionHandler(expandChrome);
  }, [expandChrome]);

  useEffect(() => {
    const previous = previousDetailTrayOpenRef.current;
    if (previous !== detailTrayOpen) {
      logDetailTrayDiagnostic('detail tray state changed', {
        previous,
        current: detailTrayOpen,
        displaySourceId: displaySource?.agentTaskId ?? null,
        selectedDetailId: selectedDetail?.detailId ?? null,
      });
      previousDetailTrayOpenRef.current = detailTrayOpen;
    }
  }, [detailTrayOpen, displaySource?.agentTaskId, selectedDetail?.detailId]);

  useEffect(() => {
    logDetailTrayDiagnostic('display source reset closes detail tray', {
      displaySourceId: displaySource?.agentTaskId ?? null,
    });
    setSelectedDetail(null);
    setFollowLatestDetail(false);
    setDetailTrayMode('overview');
    setDetailTrayOpen(false);
    // This reset is intentionally keyed to task identity only. The tray-mode
    // callback changes identity after the first user resize because that drag
    // marks its width as user-controlled; treating that callback change as a
    // new display source closed the tray mid-drag. React state setters are
    // stable, and the current callback closure is used whenever the task id
    // actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displaySource?.agentTaskId]);

  useAgentStatusReporting({
    focusedAgent: displaySource,
    selectedScheduledAgentTaskId,
    createScheduledMode,
  });

  // Clear historical/scheduled views whenever a live agent gets selected.
  useEffect(() => {
    if (selectedAgent) {
      setViewedDetail(null);
      setSelectedScheduledAgentTaskId(null);
      setCreateScheduledMode(false);
    }
  }, [selectedAgent?.agentTaskId]);

  // Long-running jobs can outlive transient WebSocket issues or reloads. While
  // the focused row still looks active locally, reconcile it against backend
  // state so a missed final result cannot leave the UI pinned forever.
  //
  // This also has to poll runs beyond just isActive: once a follow-up turn
  // begins, the root's *own* backend record is already terminal (its turn
  // finished earlier in the chain), so hydrating the root alone can never
  // resolve a missed terminal event for the *active child* turn -- it's the
  // child's own status that's stale. hasActiveFollowUpTurn keeps this effect
  // running in that case, and hydrateActiveFollowUpChild fetches the child
  // directly and applies it onto the root once it has actually finished.
  useEffect(() => {
    const agentTaskId = selectedAgent?.agentTaskId;
    const isActive = isInFlightAgentStatus(selectedAgent?.status);
    const hasActiveFollowUp = !!agentTaskId && agentStore.hasActiveFollowUpTurn(agentTaskId);
    const needsCheckpointRecovery = selectedAgent?.status === 'awaitingInput'
      && !selectedAgent.currentCheckpoint
      && !selectedAgent.showApprovalPrompt;

    const isPaused = selectedAgent?.status === 'paused';
    if (!agentTaskId || (!isActive && !hasActiveFollowUp && !needsCheckpointRecovery && !isPaused)) return;

    const reconcile = () => {
      hydrateAgentFromBackend(agentTaskId);
      const activeFollowUpId = agentStore.getActiveFollowUpId(agentTaskId);
      if (activeFollowUpId) {
        hydrateActiveFollowUpChild(agentTaskId, activeFollowUpId);
      }
    };

    reconcile();

    const interval = setInterval(reconcile, 5000);

    return () => clearInterval(interval);
  }, [selectedAgent?.agentTaskId, selectedAgent?.status]);

  useEffect(() => {
    if (!selectedDetail) {
      return;
    }
    if (!selectedCandidate) {
      setSelectedDetail(null);
      return;
    }
    if (
      detailTrayOpen
      && followLatestDetail
      && latestForOwner
      && (
        selectedDetail.ownerTaskId !== latestForOwner.ownerTaskId
        || selectedDetail.detailId !== latestForOwner.detail.id
      )
    ) {
      setSelectedDetail({
        ownerTaskId: latestForOwner.ownerTaskId,
        detailId: latestForOwner.detail.id,
      });
    }
  }, [
    detailTrayOpen,
    followLatestDetail,
    latestForOwner?.detail.id,
    latestForOwner?.ownerTaskId,
    selectedCandidate?.detail.id,
    selectedDetail,
  ]);

  const isCapturing = captureState?.isCapturing ?? false;
  const isProcessing = displaySource
    ? isInFlightAgentStatus(displaySource.status)
    : initiallyProcessing;
  const displaySourceDetached = isDisplaySourceDetached(displaySource, detachedRootsElsewhere);
  const detachedDisplayRootId = displaySource ? effectiveRootId(displaySource) : null;

  const isVerifying = displaySource ? deriveRunPhase(displaySource).kind === 'verifying' : false;

  let bubbleMode: BubbleMode = 'ambient';
  if (isCapturing) bubbleMode = 'audioResponsive';
  else if (isProcessing || isVerifying) bubbleMode = 'processing';

  const handleStartFollowUp = useCallback(() => {
    if (!displaySource) return;
    const parentId = displaySource.rootTaskId || displaySource.agentTaskId;
    agentStore.setPendingFollowUpParent(parentId);
    const previousTaskId = agentStore.getAgent(parentId)
      ? agentStore.getCurrentTurnTaskId(parentId)
      : displaySource.currentTurnTaskId || displaySource.agentTaskId;
    startFollowUpCapture(parentId, previousTaskId);
  }, [displaySource]);

  const handleRetry = useCallback(async (modelId?: string) => {
    if (!displaySource) return;
    const rootTaskId = displaySource.rootTaskId || displaySource.agentTaskId;
    const executionTaskId = agentStore.getAgent(rootTaskId)
      ? agentStore.getCurrentTurnTaskId(rootTaskId)
      : displaySource.agentTaskId;
    try {
      if (!agentStore.getAgent(rootTaskId)) {
        agentStore.registerAgent(rootTaskId, displaySource.originalPrompt);
      } else if (displaySource.originalPrompt) {
        agentStore.updateAgentTaskText(rootTaskId, displaySource.originalPrompt);
      }
      if (modelId) {
        agentStore.setSelectedModelId(rootTaskId, modelId);
      }
      setViewedDetail(null);
      agentStore.selectAgent(rootTaskId);
      agentStore.resetForRetry(rootTaskId);
      agentStore.updateProgressStep(rootTaskId, 'Retrying...', true, false);
      await api.retryAgentTask(executionTaskId, modelId);
    } catch (err) {
      console.error('[App] Retry failed:', err);
      agentStore.setError(rootTaskId, 'Retry failed');
    }
  }, [displaySource]);

  const handleContinue = useCallback(async () => {
    if (!selectedAgent) return;
    const rootTaskId = selectedAgent.rootTaskId || selectedAgent.agentTaskId;
    const currentTurnTaskId = agentStore.getCurrentTurnTaskId(rootTaskId);
    try {
      agentStore.updateStatus(rootTaskId, 'processing');
      await api.continueSession(currentTurnTaskId, 'continue');
    } catch (err) {
      console.error('[App] Continue failed:', err);
    }
  }, [selectedAgent]);

  const handleCancelRunningAgent = useCallback(() => {
    if (!selectedAgent) return;
    const rootTaskId = selectedAgent.rootTaskId || selectedAgent.agentTaskId;
    const currentTurnTaskId = agentStore.getCurrentTurnTaskId(rootTaskId);
    beginRunningAgentCancellation(
      agentStore,
      rootTaskId,
      currentTurnTaskId,
      cancelRunningAgentTask,
    );
  }, [selectedAgent]);

  const handleSelectDetail = useCallback((ownerTaskId: string, detail: StepDetailEntry, isLatest: boolean) => {
    openDetailTray('detail');
    setSelectedDetail({ ownerTaskId, detailId: detail.id });
    setFollowLatestDetail(isLatest);
  }, [openDetailTray]);

  const handleOpenRunOverview = useCallback((mode: 'overview' | 'preview' | 'detail' = 'overview') => {
    setSelectedDetail(null);
    setFollowLatestDetail(false);
    openDetailTray(mode);
  }, [openDetailTray]);

  const handleJumpToLatestDetail = useCallback(() => {
    if (!latestForOwner) return;
    setSelectedDetail({
      ownerTaskId: latestForOwner.ownerTaskId,
      detailId: latestForOwner.detail.id,
    });
    setFollowLatestDetail(true);
  }, [latestForOwner]);

  return (
    <AgentTaskResultBody
      rootRef={rootRef}
      embedded={embedded}
      isChromeCollapsed={isChromeCollapsed}
      detachedRootTaskId={detachedRootTaskId}
      displaySourceDetached={displaySourceDetached}
      detachedDisplayRootId={detachedDisplayRootId}
      detachedRootsElsewhere={detachedRootsElsewhere}
      detailTrayOpen={detailTrayOpen}
      detailTrayWidth={detailTrayWidth}
      onDetailTrayWidthChange={setDetailTrayWidth}
      onDetailTrayModeChange={setDetailTrayMode}
      onDetailTrayResizingChange={setTrayResizing}
      displaySource={displaySource}
      selectedAgent={selectedAgent}
      selectedDetail={selectedDetailEntry}
      selectedDetailId={selectedDetail?.detailId || null}
      selectedDetailOwnerId={selectedOwnerId}
      followLatestDetail={followLatestDetail}
      hasNewerDetail={hasNewerDetail}
      sidebarExpanded={sidebarExpanded}
      initialized={initialized}
      initiallyProcessing={initiallyProcessing}
      selectedScheduledAgentTaskId={selectedScheduledAgentTaskId}
      createScheduledMode={createScheduledMode}
      scheduledListVersion={scheduledListVersion}
      viewedDetail={viewedDetail}
      pendingAgentTaskSelection={pendingAgentTaskSelection}
      missedRunToasts={missedRunToasts}
      captureState={captureState}
      textFollowUpMode={textFollowUpMode}
      isProcessing={isProcessing}
      isVerifying={isVerifying}
      isCapturing={isCapturing}
      bubbleMode={bubbleMode}
      isCollapseIconRotated={isCollapseIconRotated}
      showCancelStop={isInFlightAgentStatus(selectedAgent?.status) || selectedAgent?.status === 'paused'}
      onCancelRunningAgent={handleCancelRunningAgent}
      onToggleChromeCollapsed={() => {
        logDetailTrayDiagnostic('chrome-collapse toggle invoked', {
          detailTrayOpen,
          displaySourceId: displaySource?.agentTaskId ?? null,
        });
        handleToggleChromeCollapsed();
      }}
      onToggleSidebar={() => setSidebarExpanded(expanded => !expanded)}
      onViewHistoricalAgentTask={handleViewHistoricalAgentTask}
      onViewScheduledAgentTask={handleViewScheduledAgentTask}
      onCreateScheduledAgentTask={handleCreateScheduledAgentTask}
      onAgentTaskDeleted={handleAgentTaskDeleted}
      onScheduledCreated={(id) => {
        setSelectedScheduledAgentTaskId(id);
        setCreateScheduledMode(false);
        setScheduledListVersion(version => version + 1);
      }}
      onScheduledUpdated={() => setScheduledListVersion(version => version + 1)}
      onExitCreateMode={() => setCreateScheduledMode(false)}
      onViewAgentTask={handleViewAgentTask}
      onRetry={handleRetry}
      onContinue={handleContinue}
      onSelectDetail={handleSelectDetail}
      onCancelTextFollowUp={() => setTextFollowUpMode(false)}
      onStartVoiceFollowUp={handleStartFollowUp}
      onOpenDetailTray={handleOpenRunOverview}
      onCloseDetailTray={() => {
        logDetailTrayDiagnostic('close detail tray callback invoked', {
          detailTrayOpen,
          displaySourceId: displaySource?.agentTaskId ?? null,
        });
        setDetailTrayOpen(false);
      }}
      onJumpToLatestDetail={handleJumpToLatestDetail}
      validationRunRequest={validationRunRequest}
      validationManagedHistoryRestoreRequestId={validationManagedHistoryRestoreRequestId}
    />
  );
}
