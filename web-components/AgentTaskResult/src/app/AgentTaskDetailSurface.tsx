import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { TransitionEvent } from 'react';
import type {
  AgentState,
  CaptureStateMessage,
  DisplayableAgentTask,
  StepDetailEntry,
  ValidationRunFocusRequest,
} from '../types';
import ResultContent from '../components/ResultContent';
import ProgressOverlay from '../components/ProgressOverlay';
import ApprovalSetOverlay from '../components/ApprovalSetOverlay';
import CheckpointFlow from '../components/CheckpointFlow';
import InlineCapture from '../components/InlineCapture';
import TextFollowUp from '../components/TextFollowUp';
import ExecutionDetailTray from '../components/ExecutionDetailTray';
import { deriveAgentTaskArtifacts } from '../components/artifacts/artifactDerivation';
import {
  canProbeLiveArtifactPreview,
  hasCurrentArtifactFile,
  selectArtifactsForPreview,
} from '../components/artifacts/artifactPreviewEligibility';
import {
  artifactReviewFingerprint,
  recordArtifactReviewFingerprints,
  selectArtifactForAutoOpen,
} from '../components/artifacts/artifactReviewAutoOpen';
import { deriveAgentRunOverviewPresentation, deriveAgentRunPresentation } from '../components/run/agentRunPresentation';
import { deriveAgentTaskRunFocusSummaries, resolveFocusedRun } from '../components/run/agentTaskRunFocus';
import { AgentRunRail } from '../components/run/AgentRunRail';
import { checkFilePreviewAvailability, reportValidationRunFocused } from '../services/bridge';
import { usePresenceTransition } from '@shared/usePresenceTransition';

interface Props {
  displaySource: DisplayableAgentTask;
  selectedAgent: AgentState | null;
  detailTrayOpen: boolean;
  detailTrayWidth: number;
  onDetailTrayWidthChange: (width: number) => void;
  onDetailTrayModeChange: (mode: 'overview' | 'detail' | 'preview') => void;
  onDetailTrayResizingChange?: (isResizing: boolean) => void;
  selectedDetail: StepDetailEntry | undefined;
  selectedDetailId: string | null;
  selectedDetailOwnerId: string | null;
  followLatestDetail: boolean;
  hasNewerDetail: boolean;
  textFollowUpMode: boolean;
  isProcessing: boolean;
  captureState: CaptureStateMessage | null;
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

export function AgentTaskDetailSurface({
  displaySource,
  selectedAgent,
  detailTrayOpen,
  detailTrayWidth,
  onDetailTrayWidthChange,
  onDetailTrayModeChange,
  onDetailTrayResizingChange,
  selectedDetail,
  selectedDetailId,
  selectedDetailOwnerId,
  followLatestDetail,
  hasNewerDetail,
  textFollowUpMode,
  isProcessing,
  captureState,
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
}: Props) {
  const [artifactPreviewId, setArtifactPreviewId] = useState<string>();
  const [focusedRunId, setFocusedRunId] = useState<string>();
  const [showRunOverview, setShowRunOverview] = useState(false);
  const [availablePreviewPaths, setAvailablePreviewPaths] = useState<Set<string>>(new Set());
  const [isPreviewAvailabilityResolved, setIsPreviewAvailabilityResolved] = useState(false);
  const [previewAvailabilityRunId, setPreviewAvailabilityRunId] = useState<string>();
  const seenReviewFingerprints = useRef(new Map<string, string>());
  const dismissedReviewFingerprints = useRef(new Map<string, string>());
  const hasReviewBaseline = useRef(false);
  const lastReportedValidationRequestId = useRef<string>();
  const runs = useMemo(
    () => deriveAgentTaskRunFocusSummaries(displaySource, isProcessing),
    [
      displaySource,
      displaySource.agentTaskHistory,
      displaySource.agentTaskHistory.length,
      displaySource.executionTimeline,
      displaySource.executionTimeline.length,
      displaySource.originalPrompt,
      displaySource.outcome,
      displaySource.status,
      displaySource.structuredFiles,
      displaySource.structuredFiles.length,
      displaySource.timestamp,
      isProcessing,
    ],
  );
  const focusedRun = useMemo(
    () => resolveFocusedRun(runs, focusedRunId),
    [runs, focusedRunId],
  );
  const artifacts = useMemo(
    () => deriveAgentTaskArtifacts(focusedRun.structuredFiles, focusedRun.executionTimeline),
    [focusedRun.executionTimeline, focusedRun.structuredFiles],
  );
  const previewArtifacts = useMemo(
    () => selectArtifactsForPreview(artifacts.all, availablePreviewPaths),
    [artifacts.all, availablePreviewPaths],
  );
  const previewArtifactGroups = useMemo(() => ({
    all: previewArtifacts,
    produced: previewArtifacts.filter(artifact => artifact.group === 'produced'),
    retrieved: previewArtifacts.filter(artifact => artifact.group === 'retrieved'),
    ungrouped: previewArtifacts.filter(artifact => artifact.group === 'ungrouped'),
  }), [previewArtifacts]);
  const runPresentation = useMemo(
    () => deriveAgentRunPresentation(
      focusedRun.executionTimeline,
      focusedRun.taskStatus,
      focusedRun.isProcessing,
      focusedRun.outcome,
    ),
    [focusedRun.executionTimeline, focusedRun.isProcessing, focusedRun.outcome, focusedRun.taskStatus],
  );
  const previewArtifact = previewArtifacts.find(artifact => artifact.artifactId === artifactPreviewId);
  const isPreviewArtifactFileAvailable = Boolean(
    previewArtifact
    && isPreviewAvailabilityResolved
    && hasCurrentArtifactFile(previewArtifact)
    && availablePreviewPaths.has(previewArtifact.localPath),
  );
  const runOverview = useMemo(
    () => deriveAgentRunOverviewPresentation(runPresentation),
    [runPresentation],
  );
  const hasRunRailContent = useMemo(
    () => runs.some(run => {
      const presentation = deriveAgentRunPresentation(
        run.executionTimeline,
        run.taskStatus,
        run.isProcessing,
        run.outcome,
      );
      return deriveAgentRunOverviewPresentation(presentation).stages.length > 0 || run.documentCount > 0;
    }),
    [runs],
  );
  const trayPresence = usePresenceTransition(detailTrayOpen);
  const railPresence = usePresenceTransition(!detailTrayOpen && hasRunRailContent);
  const approvalVisible = Boolean(
    selectedAgent?.showApprovalPrompt && selectedAgent.approvalRequests.length,
  );
  const checkpointVisible = Boolean(selectedAgent?.showCheckpointPrompt && selectedAgent.currentCheckpoint);
  const inlineCheckpointVisible = Boolean(selectedAgent?.inlineCheckpoint && !selectedAgent.showCheckpointPrompt);
  const followUpVisible = textFollowUpMode || displaySource.status === 'completed' || displaySource.status === 'failed';
  const approvalPresence = usePresenceTransition(approvalVisible);
  const checkpointPresence = usePresenceTransition(checkpointVisible);
  const inlineCheckpointPresence = usePresenceTransition(inlineCheckpointVisible);
  const followUpPresence = usePresenceTransition(followUpVisible);
  const retainedApprovals = useRef(selectedAgent?.approvalRequests ?? []);
  const retainedCheckpoint = useRef(selectedAgent?.currentCheckpoint);
  const retainedInlineCheckpoint = useRef(selectedAgent?.inlineCheckpoint);
  const retainedInteractiveAgentId = useRef(selectedAgent?.agentTaskId);
  const retainedRememberApprovalChoice = useRef(selectedAgent?.rememberApprovalChoice ?? false);
  if (approvalVisible) retainedApprovals.current = selectedAgent?.approvalRequests ?? [];
  if (checkpointVisible) retainedCheckpoint.current = selectedAgent?.currentCheckpoint;
  if (inlineCheckpointVisible) retainedInlineCheckpoint.current = selectedAgent?.inlineCheckpoint;
  if (selectedAgent?.agentTaskId) retainedInteractiveAgentId.current = selectedAgent.agentTaskId;
  if (approvalVisible) retainedRememberApprovalChoice.current = selectedAgent?.rememberApprovalChoice ?? false;
  const selectedArtifactId = selectedDetailOwnerId === displaySource.agentTaskId
    ? selectedDetail?.artifact?.artifactId
    : undefined;

  const openTray = useCallback((mode: 'overview' | 'detail' | 'preview', artifactId?: string) => {
    setShowRunOverview(mode === 'overview');
    setArtifactPreviewId(mode === 'preview' ? artifactId : undefined);
    onDetailTrayModeChange(mode);
    onOpenDetailTray(mode);
  }, [onDetailTrayModeChange, onOpenDetailTray]);

  const closeTray = useCallback(() => {
    onCloseDetailTray();
  }, [onCloseDetailTray]);

  useEffect(() => {
    if (!validationRunRequest) return;
    const requestedRunId = validationRunRequest.runId;
    if (requestedRunId && !runs.some(run => run.id === requestedRunId)) return;

    if (requestedRunId && focusedRun.id !== requestedRunId) {
      setFocusedRunId(requestedRunId);
      setArtifactPreviewId(undefined);
      openTray('overview');
      return;
    }

    if (!showRunOverview || !detailTrayOpen) {
      setArtifactPreviewId(undefined);
      openTray('overview');
      return;
    }

    if (
      !isPreviewAvailabilityResolved
      || previewAvailabilityRunId !== focusedRun.id
      || lastReportedValidationRequestId.current === validationRunRequest.requestId
    ) {
      return;
    }

    reportValidationRunFocused({
      requestId: validationRunRequest.requestId,
      rootTaskId: displaySource.rootTaskId || displaySource.agentTaskId,
      runId: focusedRun.id,
      requestText: focusedRun.requestText,
      resultText: focusedRun.resultText,
      documentPaths: focusedRun.structuredFiles.map(file => file.path),
      artifactIds: artifacts.all.map(artifact => artifact.artifactId),
      previewArtifactId: previewArtifact?.artifactId ?? null,
      isOverviewOpen: showRunOverview && detailTrayOpen,
    });
    lastReportedValidationRequestId.current = validationRunRequest.requestId;
  }, [
    artifacts.all,
    detailTrayOpen,
    displaySource.agentTaskId,
    displaySource.rootTaskId,
    focusedRun,
    isPreviewAvailabilityResolved,
    openTray,
    previewArtifact?.artifactId,
    previewAvailabilityRunId,
    runs,
    showRunOverview,
    validationRunRequest,
  ]);

  useEffect(() => {
    if (!validationManagedHistoryRestoreRequestId) return;
    const managedHistoryArtifact = previewArtifacts.find(
      artifact => artifact.displayName === 'managed-history-fixture.txt',
    );
    if (!managedHistoryArtifact || previewArtifact?.artifactId === managedHistoryArtifact.artifactId) return;
    openTray('preview', managedHistoryArtifact.artifactId);
  }, [
    openTray,
    previewArtifact?.artifactId,
    previewArtifacts,
    validationManagedHistoryRestoreRequestId,
  ]);

  const handleTrayTransitionEnd = useCallback((event: TransitionEvent<HTMLElement>) => {
    trayPresence.completeTransition(event);
    if (trayPresence.phase !== 'exiting' || event.target !== event.currentTarget) return;
    setArtifactPreviewId(undefined);
    setShowRunOverview(false);
  }, [trayPresence]);

  useEffect(() => {
    setFocusedRunId(undefined);
    setArtifactPreviewId(undefined);
    setShowRunOverview(true);
    seenReviewFingerprints.current = new Map();
    dismissedReviewFingerprints.current = new Map();
    hasReviewBaseline.current = false;
  }, [displaySource.agentTaskId]);

  // A follow-up keeps the root agentTaskId and only swaps currentTurnTaskId, so the reset above never fires for a new turn.
  const currentTurnRunId = displaySource.currentTurnTaskId || displaySource.agentTaskId;
  useEffect(() => {
    setFocusedRunId(undefined);
  }, [currentTurnRunId]);

  useEffect(() => {
    setArtifactPreviewId(undefined);
    setAvailablePreviewPaths(new Set());
    setIsPreviewAvailabilityResolved(false);
    setPreviewAvailabilityRunId(undefined);
    hasReviewBaseline.current = false;
  }, [focusedRun.id]);

  useEffect(() => {
    const runId = focusedRun.id;
    const candidatePaths = artifacts.all
      .filter(canProbeLiveArtifactPreview)
      .map(artifact => artifact.localPath);
    let isCurrent = true;

    void checkFilePreviewAvailability(candidatePaths)
      .then(availablePaths => {
        if (!isCurrent) return;
        setAvailablePreviewPaths(availablePaths);
        setIsPreviewAvailabilityResolved(true);
        setPreviewAvailabilityRunId(runId);
      })
      .catch(() => {
        if (!isCurrent) return;
        setAvailablePreviewPaths(new Set());
        setIsPreviewAvailabilityResolved(true);
        setPreviewAvailabilityRunId(runId);
      });

    return () => {
      isCurrent = false;
    };
  }, [artifacts.all, focusedRun.id]);

  useEffect(() => {
    if (!isPreviewAvailabilityResolved || previewAvailabilityRunId !== focusedRun.id) return;
    if (!hasReviewBaseline.current) {
      recordArtifactReviewFingerprints(previewArtifactGroups.produced, seenReviewFingerprints.current);
      hasReviewBaseline.current = true;
      return;
    }
    const autoOpenArtifactId = selectArtifactForAutoOpen(
      previewArtifactGroups.produced,
      seenReviewFingerprints.current,
      dismissedReviewFingerprints.current,
    );
    if (!autoOpenArtifactId) return;
    openTray('preview', autoOpenArtifactId);
  }, [
    focusedRun.id,
    isPreviewAvailabilityResolved,
    openTray,
    previewArtifactGroups.produced,
    previewAvailabilityRunId,
  ]);

  useEffect(() => {
    setShowRunOverview(false);
  }, [selectedDetail?.id, selectedDetailOwnerId]);

  useEffect(() => {
    if (!selectedArtifactId || !previewArtifacts.some(artifact => artifact.artifactId === selectedArtifactId)) return;
    openTray('preview', selectedArtifactId);
  }, [openTray, previewArtifacts, selectedArtifactId]);

  useEffect(() => {
    if (artifactPreviewId && !previewArtifact) setArtifactPreviewId(undefined);
  }, [artifactPreviewId, previewArtifact]);

  const handlePreviewArtifact = (artifactId: string) => {
    openTray('preview', artifactId);
  };

  const handleFocusRun = (runId: string) => {
    setFocusedRunId(runId);
  };

  const isRunOverviewVisible = detailTrayOpen && showRunOverview;

  const handleFocusRunFromContent = (runId: string) => {
    if (isRunOverviewVisible && focusedRun.id === runId) {
      closeTray();
      return;
    }
    setFocusedRunId(runId);
    openTray('overview');
  };

  const handleOpenRunOverview = () => {
    openTray('overview');
  };

  const handleCloseRunPanel = () => {
    closeTray();
  };

  return (
    <div className={`agent-detail-layout ${detailTrayOpen ? 'tray-open' : ''}`}>
      <div className="content-area">
        <ResultContent
          agentTask={displaySource}
          onRetry={onRetry}
          onContinue={onContinue}
          selectedDetailId={selectedDetailId}
          selectedDetailOwnerId={selectedDetailOwnerId}
          onSelectDetail={onSelectDetail}
          focusedRunId={isRunOverviewVisible ? focusedRun.id : null}
          onFocusRun={handleFocusRunFromContent}
        />
        {inlineCheckpointPresence.shouldRender && retainedInlineCheckpoint.current && retainedInteractiveAgentId.current && (
          <div
            className="checkpoint-presence-region checkpoint-presence-region--inline"
            data-presence-phase={inlineCheckpointPresence.phase}
            aria-hidden={inlineCheckpointPresence.phase === 'exiting'}
            inert={inlineCheckpointPresence.phase === 'exiting' ? '' : undefined}
            onTransitionEnd={inlineCheckpointPresence.completeTransition}
            style={{ flexShrink: 0, padding: '0 var(--padding-l)' }}
          >
            <CheckpointFlow agentTaskId={retainedInteractiveAgentId.current} checkpoint={retainedInlineCheckpoint.current} mode="inline" />
          </div>
        )}
        {followUpPresence.shouldRender && (
          <div
            className="text-followup-presence-region"
            data-presence-phase={followUpPresence.phase}
            aria-hidden={followUpPresence.phase === 'exiting'}
            inert={followUpPresence.phase === 'exiting' ? '' : undefined}
            onTransitionEnd={followUpPresence.completeTransition}
            style={{ flexShrink: 0, padding: '0 var(--padding-l)', paddingBottom: 'var(--padding-s)' }}
          >
            <TextFollowUp
              agentTaskId={displaySource.agentTaskId}
              rootTaskId={displaySource.rootTaskId}
              displaySource={!selectedAgent ? displaySource : undefined}
              onCancel={onCancelTextFollowUp}
              isProcessing={isProcessing}
              exiting={followUpPresence.phase === 'exiting'}
              alwaysVisible={!textFollowUpMode}
              onStartVoiceFollowUp={onStartVoiceFollowUp}
            />
          </div>
        )}
        {captureState?.isCapturing && (
          <div style={{ flexShrink: 0, padding: '0 var(--padding-l)' }}>
            <InlineCapture captureState={captureState} />
          </div>
        )}
        <ProgressOverlay
          isProcessing={isProcessing}
          currentStep={displaySource.currentStep}
          isStepComplete={displaySource.progressSteps.find(step => step.step === displaySource.currentStep)?.isComplete}
        />
        {approvalPresence.shouldRender && retainedApprovals.current.length > 0 && retainedInteractiveAgentId.current && (
          <div
            className="approval-presence-region"
            data-presence-phase={approvalPresence.phase}
            aria-hidden={approvalPresence.phase === 'exiting'}
            inert={approvalPresence.phase === 'exiting' ? '' : undefined}
            onTransitionEnd={approvalPresence.completeTransition}
          >
            <ApprovalSetOverlay
              agentTaskId={retainedInteractiveAgentId.current}
              approvals={retainedApprovals.current}
              rememberChoice={retainedRememberApprovalChoice.current}
            />
          </div>
        )}
        {checkpointPresence.shouldRender && retainedCheckpoint.current && retainedInteractiveAgentId.current && (
          <div
            className="checkpoint-presence-region checkpoint-presence-region--overlay"
            data-presence-phase={checkpointPresence.phase}
            aria-hidden={checkpointPresence.phase === 'exiting'}
            inert={checkpointPresence.phase === 'exiting' ? '' : undefined}
            onTransitionEnd={checkpointPresence.completeTransition}
          >
            <CheckpointFlow agentTaskId={retainedInteractiveAgentId.current} checkpoint={retainedCheckpoint.current} mode="overlay" />
          </div>
        )}
      </div>
      {railPresence.shouldRender && (
        <div
          className="agent-run-rail-presence"
          data-presence-phase={railPresence.phase}
          aria-hidden={railPresence.phase !== 'present'}
          onTransitionEnd={railPresence.completeTransition}
        >
          <AgentRunRail
            overview={runOverview}
            artifactCount={previewArtifactGroups.produced.length}
            runId={focusedRun.id}
            isProcessing={focusedRun.isProcessing}
            onExpand={handleOpenRunOverview}
          />
        </div>
      )}
      <ExecutionDetailTray
        isOpen={trayPresence.shouldRender}
        presencePhase={trayPresence.phase}
        onPresenceTransitionEnd={handleTrayTransitionEnd}
        trayWidth={detailTrayWidth}
        onTrayWidthChange={onDetailTrayWidthChange}
        onResizingChange={onDetailTrayResizingChange}
        detail={showRunOverview ? undefined : selectedDetail}
        followLatest={followLatestDetail}
        hasNewerDetail={hasNewerDetail}
        onClose={onCloseDetailTray}
        onJumpToLatest={onJumpToLatestDetail}
        artifacts={previewArtifactGroups}
        timeline={displaySource.executionTimeline}
        runPresentation={runPresentation}
        overviewPresentation={runOverview}
        isProcessing={isProcessing}
        terminalStatus={displaySource.status}
        agentTaskId={focusedRun.id}
        rootTaskId={displaySource.rootTaskId || displaySource.agentTaskId}
        focusedRunId={focusedRun.id}
        previewArtifact={previewArtifact}
        isPreviewArtifactFileAvailable={isPreviewArtifactFileAvailable}
        onPreviewArtifact={handlePreviewArtifact}
        runs={runs}
        onFocusRun={handleFocusRun}
        onClosePreview={() => {
          if (previewArtifact) {
            dismissedReviewFingerprints.current.set(
              previewArtifact.artifactId,
              artifactReviewFingerprint(previewArtifact),
            );
          }
          openTray('overview');
        }}
        onCloseRunPanel={handleCloseRunPanel}
      />
    </div>
  );
}
