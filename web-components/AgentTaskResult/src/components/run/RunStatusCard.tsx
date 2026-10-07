import { useEffect, useState } from 'react';
import type { DisplayableAgentTask, StepDetailEntry } from '../../types';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import MarkdownRenderer from '../MarkdownRenderer';
import NativeSymbolIcon from '../../../../shared/NativeSymbolIcon';
import ReasoningModelPicker from '../../../../shared/ReasoningModelPicker';
import { getReasoningModels, type ReasoningModel } from '../../services/api';
import { normalizeProgressStepText } from '../result/progressStepText';
import { ProgressStepsSection, type ActivityStatusDisplay } from '../result/ExecutionTimeline';
import type { RunPhase } from './runPhase';

interface RunStatusCardProps {
  agentTask: DisplayableAgentTask;
  phase: RunPhase;
  /** When true the activity trail lives in this card; otherwise the finished-turn Activity row owns it. */
  showTrail: boolean;
  selectedDetailId?: string | null;
  onSelectDetail?: (detail: StepDetailEntry, isLatest: boolean) => void;
  hasUnreadLiveContent: boolean;
  onJumpToLatestContent: () => void;
  onRetry: (modelId?: string) => void;
  onContinue: () => void;
}

const VERIFYING_NOTE = 'Checking the response against your request. The result is provisional until this finishes.';
const CANCELED_NOTE = 'This run was canceled before it finished. Nothing more will happen unless you run it again.';
const UNEXPLAINED_FAILURE_NOTE = 'The run ended without completing and did not report a reason.';

function useElapsedSeconds(active: boolean, resetKey: string): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    setSeconds(0);
    if (!active) return undefined;
    const startedAt = Date.now();
    const interval = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [active, resetKey]);
  return seconds;
}

function firstMeaningfulLine(text: string | undefined): string {
  return plainMarkdownText(text ?? '')
    .split('\n')
    .map(line => line.trim())
    .find(Boolean) ?? '';
}

function collapsedPlainText(text: string | undefined): string {
  return plainMarkdownText(text ?? '').replace(/\s+/g, ' ').trim();
}

/** A partial run's error text is often the same message the Result section already shows; repeating it in the card adds nothing. */
export function reasonRepeatsResult(errorMessage: string | undefined, result: string | undefined): boolean {
  const reason = collapsedPlainText(errorMessage);
  const shown = collapsedPlainText(result);
  if (!reason || !shown) return false;
  return reason === shown || shown.includes(reason) || reason.includes(shown);
}

function reasonFor(agentTask: DisplayableAgentTask, phase: RunPhase): string {
  if (phase.kind === 'canceled') return CANCELED_NOTE;
  if (phase.kind === 'verifying') return VERIFYING_NOTE;
  if (phase.kind === 'settled' && phase.outcome !== 'success') {
    if (reasonRepeatsResult(agentTask.errorMessage, agentTask.result)) return '';
    return agentTask.errorMessage?.trim() || UNEXPLAINED_FAILURE_NOTE;
  }
  return '';
}

function statusFor(
  agentTask: DisplayableAgentTask,
  phase: RunPhase,
  elapsedSeconds: number,
): ActivityStatusDisplay {
  const fallbackSummary = agentTask.currentStep ? normalizeProgressStepText(agentTask.currentStep) : undefined;
  switch (phase.kind) {
    case 'working':
      return { tone: 'live', label: phase.label, fallbackSummary };
    case 'verifying':
      return { tone: 'live', label: phase.label, detail: `${elapsedSeconds}s`, fallbackSummary };
    case 'paused':
      return { tone: 'attention', label: phase.label, fallbackSummary };
    case 'awaiting':
      return { tone: 'attention', label: phase.label, fallbackSummary };
    case 'canceled':
      return { tone: 'neutral', label: phase.label, summary: 'Stopped before finishing', openByDefault: true };
    default:
      return {
        tone: phase.outcome === 'partial' ? 'attention' : 'danger',
        label: phase.label,
        summary: reasonRepeatsResult(agentTask.errorMessage, agentTask.result)
          ? 'Details are in the result above'
          : firstMeaningfulLine(agentTask.errorMessage) || 'No reason was reported',
        openByDefault: true,
      };
  }
}

function RecoveryActions({
  agentTask,
  isCanceled,
  onRetry,
  onContinue,
}: {
  agentTask: DisplayableAgentTask;
  isCanceled: boolean;
  onRetry: (modelId?: string) => void;
  onContinue: () => void;
}) {
  const [models, setModels] = useState<ReasoningModel[]>([]);
  const [modelId, setModelId] = useState<string | undefined>(
    agentTask.selectedModelId ?? agentTask.originalModelId,
  );

  useEffect(() => {
    let canceled = false;
    getReasoningModels()
      .then(data => {
        if (canceled) return;
        setModels(data.models);
        setModelId(current => current ?? data.current_model);
      })
      .catch(error => console.error('[RunStatusCard] Failed to load models:', error));
    return () => {
      canceled = true;
    };
  }, []);

  return (
    <div className="result-actions run-status-actions">
      {agentTask.checkpointAvailable && (
        <button type="button" className="action-btn primary" onClick={onContinue}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M5.5 3.5v9l7-4.5z" />
          </svg>
          {' '}Continue
        </button>
      )}
      <ReasoningModelPicker
        models={models}
        selectedModelId={modelId}
        disabled={false}
        onModelChange={setModelId}
        ariaLabel="Retry model"
        placeholder="Model"
      />
      <button type="button" className="action-btn primary" onClick={() => onRetry(modelId)}>
        <NativeSymbolIcon name="retry" style={{ verticalAlign: '-2px' }} />
        {' '}{isCanceled ? 'Run again' : 'Retry'}
      </button>
    </div>
  );
}

export function RunStatusCard({
  agentTask,
  phase,
  showTrail,
  selectedDetailId,
  onSelectDetail,
  hasUnreadLiveContent,
  onJumpToLatestContent,
  onRetry,
  onContinue,
}: RunStatusCardProps) {
  const elapsedSeconds = useElapsedSeconds(phase.kind === 'verifying', agentTask.agentTaskId);
  const status = statusFor(agentTask, phase, elapsedSeconds);
  const reason = reasonFor(agentTask, phase);
  const showRecovery = phase.offersRecovery && !agentTask.isStreaming;
  const showReasonAsMarkdown = phase.kind === 'settled';

  const footer = reason || showRecovery ? (
    <>
      {reason ? (
        showReasonAsMarkdown ? (
          <div className="run-status-reason error-markdown">
            <MarkdownRenderer content={reason} />
          </div>
        ) : (
          <p className="run-status-note">{reason}</p>
        )
      ) : null}
      {showRecovery ? (
        <RecoveryActions
          agentTask={agentTask}
          isCanceled={phase.kind === 'canceled'}
          onRetry={onRetry}
          onContinue={onContinue}
        />
      ) : null}
    </>
  ) : undefined;

  return (
    <ProgressStepsSection
      presentation="dock"
      steps={agentTask.progressSteps}
      timeline={agentTask.executionTimeline}
      stepDetails={agentTask.stepDetails}
      selectedDetailId={selectedDetailId}
      onSelectDetail={onSelectDetail}
      isProcessing={phase.isBusy}
      hasUnreadLiveContent={hasUnreadLiveContent}
      onJumpToLatestContent={onJumpToLatestContent}
      status={status}
      statusFooter={footer}
      showTrail={showTrail}
    />
  );
}
