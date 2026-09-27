import { memo, useEffect, useRef } from 'react';
import { openExistingAgentTaskWidget } from '../services/bridge';
import type { ConversationMessageItem } from '../contracts';
import {
  conversationAgentTurnMetadata,
  isTerminalConversationAgentStatusLifecycle,
} from './conversationAgentStatusPresentation';
import {
  conversationAgentActivityMetadata,
  type ConversationAgentActivityPresentation,
} from './conversationAgentActivityPresentation';

interface AgentTaskStatusCardProps {
  message: ConversationMessageItem;
  onPreviewArtifact: (agentTaskId: string, artifactId: string) => void;
  onViewAllArtifacts: (agentTaskId: string) => void;
}

const LIFECYCLE_LABEL: Record<string, string> = {
  pending: 'Preparing agent task',
  running: 'Agent task in progress',
  completed: 'Agent task completed',
  failed: 'Agent task failed',
  cancelled: 'Agent task cancelled',
};

const LIFECYCLE_ICON: Record<string, string> = {
  pending: '\u22EF',
  running: '\u22EF',
  completed: '\u2713',
  failed: '!',
  cancelled: '\u29B8',
};

const VERIFICATION_LABEL: Record<ConversationAgentActivityPresentation['verificationStatus'], string> = {
  pending: 'Verification pending',
  resolved: 'Verification resolved',
  unknown: 'Verification unknown',
};

function workflowLabel(activity: ConversationAgentActivityPresentation): string | undefined {
  const { completedSteps, totalSteps } = activity.workflow;
  return completedSteps === undefined || totalSteps === undefined
    ? undefined
    : `${completedSteps} of ${totalSteps} steps`;
}

function AgentTaskStatusCardComponent({
  message,
  onPreviewArtifact,
  onViewAllArtifacts,
}: AgentTaskStatusCardProps) {
  const turn = conversationAgentTurnMetadata(message);
  const activity = conversationAgentActivityMetadata(message);
  const launchedAttentionKeys = useRef(new Set<string>());
  const attentionKey = turn ? `${turn.agentTaskId}:${turn.attentionId ?? 'current'}` : undefined;

  useEffect(() => {
    if (!turn?.requiresUserAttention || !attentionKey || launchedAttentionKeys.current.has(attentionKey)) return;
    launchedAttentionKeys.current.add(attentionKey);
    openExistingAgentTaskWidget(turn.agentTaskId);
  }, [attentionKey, turn?.agentTaskId, turn?.requiresUserAttention]);

  if (!turn) return null;
  const isTerminal = isTerminalConversationAgentStatusLifecycle(turn.lifecycle);
  const isNarrating = turn.narrationState === 'narrating' || turn.narrationState === 'retrying';
  const workflow = activity ? workflowLabel(activity) : undefined;
  const statusText = isNarrating ? 'Preparing conversation response' : turn.statusText;
  const detailText = activity?.latestActivity ?? statusText;
  const showOutcome = Boolean(
    isTerminal
    && turn.terminalOutcome
    && turn.terminalOutcome.trim() !== detailText?.trim(),
  );
  const previewedArtifacts = activity?.artifacts.slice(0, 2) ?? [];

  return (
    <div
      className={`chats-agent-task-card chats-agent-task-card-${turn.lifecycle}${turn.requiresUserAttention ? ' chats-agent-task-card-needs-attention' : ''}`}
      role={turn.requiresUserAttention ? 'alert' : 'status'}
      aria-label={turn.requiresUserAttention ? 'Agent task needs your input' : LIFECYCLE_LABEL[turn.lifecycle]}
    >
      <span
        className={`chats-agent-task-icon${isTerminal ? '' : ' is-spinning'}`}
        aria-hidden="true"
      >
        {LIFECYCLE_ICON[turn.lifecycle]}
      </span>
      <div className="chats-agent-task-body">
        <span className="chats-agent-task-label">
          {turn.requiresUserAttention ? 'Agent task needs your input' : LIFECYCLE_LABEL[turn.lifecycle]}
        </span>
        {detailText ? (
          <span className="chats-agent-task-status-text">{detailText}</span>
        ) : null}
        {showOutcome ? (
          <span className="chats-agent-task-outcome">{turn.terminalOutcome}</span>
        ) : null}
        {activity ? (
          <dl className="chats-agent-task-metrics">
            {workflow ? <div><dt>Workflow</dt><dd>{workflow}</dd></div> : null}
            <div><dt>Verification</dt><dd>{VERIFICATION_LABEL[activity.verificationStatus]}</dd></div>
          </dl>
        ) : null}
        {activity && activity.artifactCount > 0 ? (
          <div className="chats-agent-task-files" aria-label="Agent task files">
            <span className="chats-agent-task-files-label">Files</span>
            <ul className="chats-agent-task-file-chips">
              {previewedArtifacts.map((artifact) => (
                <li key={artifact.artifactId}>
                  <button
                    type="button"
                    className="chats-agent-task-file-chip"
                    title={artifact.displayName}
                    onClick={() => onPreviewArtifact(turn.agentTaskId, artifact.artifactId)}
                  >
                    {artifact.displayName}
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="chats-agent-task-files-view-all"
              onClick={() => onViewAllArtifacts(turn.agentTaskId)}
            >
              {`View all (${activity.artifactCount})`}
            </button>
          </div>
        ) : null}
      </div>
      <button
        type="button"
        className="chats-agent-task-link"
        onClick={() => openExistingAgentTaskWidget(turn.agentTaskId)}
      >
        {turn.requiresUserAttention ? 'Respond in Agent Task' : 'Open Agent Task'}
      </button>
    </div>
  );
}

export default memo(AgentTaskStatusCardComponent);
