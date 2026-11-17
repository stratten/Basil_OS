import { useEffect, useState } from 'react';
import type { DisplayableAgentTask, StepDetailEntry } from '../../types';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import MarkdownRenderer from '../MarkdownRenderer';
import ReasoningModelPicker from '../../../../shared/ReasoningModelPicker';
import { ContinueCircleIcon, ReportCircleIcon, RetryCircleIcon, WorkLogCircleIcon } from '../../../../shared/CircleControlIcons';
import { getReasoningModels, type ReasoningModel } from '../../services/api';
import { reportProblem, showDiagnosticLogs } from '../../services/bridge';
import { DecisionButton } from '../interaction/DecisionButton';
import { normalizeProgressStepText } from '../result/progressStepText';
import { ProgressStepsSection, type ActivityStatusDisplay } from '../result/ExecutionTimeline';
import { statusToneOfPhase, type RunPhase } from './runPhase';
import { activitySignature, formatQuietNotice, useQuietSeconds } from './quietActivity';

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

const PROBLEM_DETAIL_LIMIT = 500;

/** The short failure text sent with a problem report, or undefined when the run reported none. */
export function problemDetailFor(agentTask: DisplayableAgentTask): string | undefined {
  const text = collapsedPlainText(agentTask.errorMessage);
  return text ? text.slice(0, PROBLEM_DETAIL_LIMIT) : undefined;
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

export function statusFor(
  agentTask: DisplayableAgentTask,
  phase: RunPhase,
  elapsedSeconds: number,
  quietSeconds = 0,
): ActivityStatusDisplay {
  const fallbackSummary = agentTask.currentStep ? normalizeProgressStepText(agentTask.currentStep) : undefined;
  const quietNotice = quietSeconds > 0 ? formatQuietNotice(quietSeconds) : undefined;
  switch (phase.kind) {
    case 'working':
      return { tone: statusToneOfPhase(phase), label: phase.label, detail: quietNotice, fallbackSummary };
    case 'verifying':
      return {
        tone: statusToneOfPhase(phase),
        label: phase.label,
        detail: quietNotice ? `${elapsedSeconds}s · ${quietNotice}` : `${elapsedSeconds}s`,
        fallbackSummary,
      };
    case 'paused':
      return { tone: statusToneOfPhase(phase), label: phase.label, fallbackSummary };
    case 'awaiting':
      return { tone: statusToneOfPhase(phase), label: phase.label, fallbackSummary };
    case 'canceled':
      return { tone: statusToneOfPhase(phase), label: phase.label, summary: 'Stopped before finishing' };
    default:
      return {
        tone: statusToneOfPhase(phase),
        label: phase.label,
        summary: reasonRepeatsResult(agentTask.errorMessage, agentTask.result)
          ? 'Details above'
          : firstMeaningfulLine(agentTask.errorMessage) || 'No reason was reported',
      };
  }
}

/** The model a retry will use. It is held in the card so the Retry icon and the picker beside it in the header row share it. Models load only while recovery is on offer. */
function useRetryModel(agentTask: DisplayableAgentTask, enabled: boolean) {
  const [models, setModels] = useState<ReasoningModel[]>([]);
  const [modelId, setModelId] = useState<string | undefined>(
    agentTask.selectedModelId ?? agentTask.originalModelId,
  );

  useEffect(() => {
    if (!enabled) return undefined;
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
  }, [enabled]);

  return { models, modelId, setModelId };
}

/** The retry model picker, compact enough to share the bar's single row. It sits just left of Retry, because it chooses the model that Retry will use. */
function RetryModelPicker({
  models,
  modelId,
  onModelChange,
}: {
  models: ReasoningModel[];
  modelId: string | undefined;
  onModelChange: (modelId: string | undefined) => void;
}) {
  return (
    <div className="run-status-picker">
      <ReasoningModelPicker
        models={models}
        selectedModelId={modelId}
        disabled={false}
        onModelChange={onModelChange}
        ariaLabel="Retry model"
        placeholder="Model"
      />
    </div>
  );
}

/** The retry model picker, then Continue, Retry, Show logs and Report a problem as the bordered icon buttons that the approval and run-control rows use. They sit in the bar's header row so the bar stays one row tall, and the tooltip on each icon names the action. */
function RecoveryActions({
  agentTask,
  isCanceled,
  models,
  modelId,
  onModelChange,
  onRetry,
  onContinue,
}: {
  agentTask: DisplayableAgentTask;
  isCanceled: boolean;
  models: ReasoningModel[];
  modelId: string | undefined;
  onModelChange: (modelId: string | undefined) => void;
  onRetry: (modelId?: string) => void;
  onContinue: () => void;
}) {
  const problemDetail = problemDetailFor(agentTask);

  return (
    <div className="run-status-recovery" role="group" aria-label="Recovery actions">
      {agentTask.checkpointAvailable && (
        <DecisionButton tone="neutral" icon={<ContinueCircleIcon />} label="Continue" title="pick up from where it stopped" onClick={onContinue} />
      )}
      <RetryModelPicker models={models} modelId={modelId} onModelChange={onModelChange} />
      <DecisionButton
        tone="neutral"
        className="run-status-retry"
        icon={<RetryCircleIcon />}
        label={isCanceled ? 'Run again' : 'Retry'}
        title="run this turn again"
        onClick={() => onRetry(modelId)}
      />
      {isCanceled ? null : (
        <>
          <DecisionButton tone="neutral" icon={<WorkLogCircleIcon />} label="Show logs" title="open the diagnostic logs for this run" onClick={() => showDiagnosticLogs(problemDetail)} />
          <DecisionButton tone="neutral" icon={<ReportCircleIcon />} label="Report a problem" title="send details about this run" onClick={() => reportProblem(problemDetail)} />
        </>
      )}
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
  const quietSeconds = useQuietSeconds(phase.isBusy, activitySignature(agentTask));
  const status = statusFor(agentTask, phase, elapsedSeconds, quietSeconds);
  const reason = reasonFor(agentTask, phase);
  const showRecovery = phase.offersRecovery && !agentTask.isStreaming;
  const retryModel = useRetryModel(agentTask, showRecovery);
  const showReasonAsMarkdown = phase.kind === 'settled';

  // The reason stays visible under the bar, so a stopped run never hides why it stopped. The recovery actions sit in the bar's own row.
  const footer = reason ? (
    showReasonAsMarkdown ? (
      <div className="run-status-reason error-markdown">
        <MarkdownRenderer content={reason} />
      </div>
    ) : (
      <p className="run-status-note">{reason}</p>
    )
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
      statusActions={showRecovery ? (
        <RecoveryActions
          agentTask={agentTask}
          isCanceled={phase.kind === 'canceled'}
          models={retryModel.models}
          modelId={retryModel.modelId}
          onModelChange={retryModel.setModelId}
          onRetry={onRetry}
          onContinue={onContinue}
        />
      ) : undefined}
      showTrail={showTrail}
    />
  );
}
