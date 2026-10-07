import type {
  ConversationAgentActivityArtifactKind,
  ConversationAgentActivityArtifactLifecycle,
  ConversationAgentActivityArtifactVerificationStatus,
  ConversationAgentActivityLifecycle,
  ConversationAgentActivityVerificationStatus,
  ConversationMessageItem,
  WSEvent,
} from '../contracts';
import { conversationAgentTurnMetadata } from './conversationAgentStatusPresentation';

const MAX_IDENTIFIER_CHARS = 256;
const MAX_TEXT_CHARS = 240;
const MAX_ARTIFACTS = 6;

const ACTIVITY_LIFECYCLES: ReadonlySet<string> = new Set([
  'capturing',
  'routing',
  'routed',
  'processing',
  'awaiting_provider_delegation',
  'awaiting_delegated_agents',
  'awaiting_user_input',
  'waiting_user_input',
  'needs_clarification',
  'clarification_added',
  'paused',
  'completed',
  'failed',
  'canceled',
]);
const ARTIFACT_KINDS: ReadonlySet<string> = new Set(['file', 'directory', 'unknown']);
const ARTIFACT_LIFECYCLES: ReadonlySet<string> = new Set([
  'discovered',
  'ready',
  'verified',
  'failed',
  'unavailable',
]);
const ARTIFACT_VERIFICATION_STATUSES: ReadonlySet<string> = new Set([
  'not_applicable',
  'pending',
  'verified',
  'failed',
  'unknown',
]);
const VERIFICATION_STATUSES: ReadonlySet<string> = new Set(['pending', 'resolved', 'unknown']);
const SUMMARY_KEYS: ReadonlySet<string> = new Set([
  'agent_task_id',
  'lifecycle',
  'latest_activity',
  'workflow',
  'artifacts',
  'artifact_count',
  'verification_status',
  'requires_user_attention',
]);
const WORKFLOW_KEYS: ReadonlySet<string> = new Set(['completed_steps', 'total_steps']);
const ARTIFACT_KEYS: ReadonlySet<string> = new Set([
  'artifact_id',
  'display_name',
  'artifact_kind',
  'lifecycle',
  'verification',
]);
const VERIFICATION_KEYS: ReadonlySet<string> = new Set(['status']);

export interface ConversationAgentActivityWorkflowPresentation {
  completedSteps?: number;
  totalSteps?: number;
}

export interface ConversationAgentActivityArtifactPresentation {
  artifactId: string;
  displayName: string;
  artifactKind: ConversationAgentActivityArtifactKind;
  lifecycle: ConversationAgentActivityArtifactLifecycle;
  verificationStatus: ConversationAgentActivityArtifactVerificationStatus;
}

export interface ConversationAgentActivityPresentation {
  agentTaskId: string;
  lifecycle: ConversationAgentActivityLifecycle;
  latestActivity?: string;
  workflow: ConversationAgentActivityWorkflowPresentation;
  artifacts: ConversationAgentActivityArtifactPresentation[];
  artifactCount: number;
  verificationStatus: ConversationAgentActivityVerificationStatus;
  requiresUserAttention: boolean;
}

export interface ConversationAgentActivityEvent {
  conversationId: string;
  placeholderMessageId: string;
  agentTaskId: string;
  summary: ConversationAgentActivityPresentation;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowedKeys: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function parseIdentifier(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim();
  return normalized && normalized.length <= MAX_IDENTIFIER_CHARS ? normalized : undefined;
}

function parseBoundedText(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim();
  return normalized && normalized.length <= MAX_TEXT_CHARS ? normalized : undefined;
}

function parseNonNegativeInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function parseWorkflow(value: unknown): ConversationAgentActivityWorkflowPresentation | undefined {
  if (!isRecord(value) || !hasOnlyKeys(value, WORKFLOW_KEYS)) return undefined;
  const hasCompletedSteps = Object.prototype.hasOwnProperty.call(value, 'completed_steps');
  const hasTotalSteps = Object.prototype.hasOwnProperty.call(value, 'total_steps');
  if (!hasCompletedSteps && !hasTotalSteps) return {};
  if (!hasCompletedSteps || !hasTotalSteps) return undefined;
  const completedSteps = parseNonNegativeInteger(value.completed_steps);
  const totalSteps = parseNonNegativeInteger(value.total_steps);
  if (completedSteps === undefined || totalSteps === undefined || completedSteps > totalSteps) return undefined;
  return { completedSteps, totalSteps };
}

function parseArtifact(value: unknown): ConversationAgentActivityArtifactPresentation | undefined {
  if (!isRecord(value) || !hasOnlyKeys(value, ARTIFACT_KEYS)) return undefined;
  const verification = value.verification;
  if (!isRecord(verification) || !hasOnlyKeys(verification, VERIFICATION_KEYS)) return undefined;
  const artifactId = parseIdentifier(value.artifact_id);
  const displayName = parseBoundedText(value.display_name);
  const artifactKind = parseIdentifier(value.artifact_kind);
  const lifecycle = parseIdentifier(value.lifecycle);
  const verificationStatus = parseIdentifier(verification.status);
  if (
    artifactId === undefined
    || displayName === undefined
    || artifactKind === undefined
    || lifecycle === undefined
    || verificationStatus === undefined
    || !ARTIFACT_KINDS.has(artifactKind)
    || !ARTIFACT_LIFECYCLES.has(lifecycle)
    || !ARTIFACT_VERIFICATION_STATUSES.has(verificationStatus)
  ) {
    return undefined;
  }
  return {
    artifactId,
    displayName,
    artifactKind: artifactKind as ConversationAgentActivityArtifactKind,
    lifecycle: lifecycle as ConversationAgentActivityArtifactLifecycle,
    verificationStatus: verificationStatus as ConversationAgentActivityArtifactVerificationStatus,
  };
}

export function parseConversationAgentActivitySummary(
  value: unknown,
): ConversationAgentActivityPresentation | undefined {
  if (!isRecord(value) || !hasOnlyKeys(value, SUMMARY_KEYS)) return undefined;
  const agentTaskId = parseIdentifier(value.agent_task_id);
  const lifecycle = parseIdentifier(value.lifecycle);
  const workflow = parseWorkflow(value.workflow);
  const artifactCount = parseNonNegativeInteger(value.artifact_count);
  const verificationStatus = parseIdentifier(value.verification_status);
  if (
    agentTaskId === undefined
    || lifecycle === undefined
    || workflow === undefined
    || artifactCount === undefined
    || verificationStatus === undefined
    || !ACTIVITY_LIFECYCLES.has(lifecycle)
    || !VERIFICATION_STATUSES.has(verificationStatus)
    || typeof value.requires_user_attention !== 'boolean'
    || !Array.isArray(value.artifacts)
    || value.artifacts.length > MAX_ARTIFACTS
  ) {
    return undefined;
  }
  const artifacts = value.artifacts.map(parseArtifact);
  if (artifacts.some((artifact) => artifact === undefined) || artifactCount < artifacts.length) return undefined;
  let latestActivity: string | undefined;
  if (Object.prototype.hasOwnProperty.call(value, 'latest_activity')) {
    latestActivity = parseBoundedText(value.latest_activity);
    if (latestActivity === undefined) return undefined;
  }
  return {
    agentTaskId,
    lifecycle: lifecycle as ConversationAgentActivityLifecycle,
    ...(latestActivity === undefined ? {} : { latestActivity }),
    workflow,
    artifacts: artifacts as ConversationAgentActivityArtifactPresentation[],
    artifactCount,
    verificationStatus: verificationStatus as ConversationAgentActivityVerificationStatus,
    requiresUserAttention: value.requires_user_attention,
  };
}

export function parseConversationAgentActivityEvent(
  event: WSEvent,
): ConversationAgentActivityEvent | undefined {
  if (event.event_type !== 'conversation_agent_activity') return undefined;
  const conversationId = parseIdentifier(event.conversation_id);
  const placeholderMessageId = parseIdentifier(event.placeholder_message_id);
  const agentTaskId = parseIdentifier(event.agent_task_id);
  const summary = parseConversationAgentActivitySummary(event.summary);
  if (
    conversationId === undefined
    || placeholderMessageId === undefined
    || agentTaskId === undefined
    || summary === undefined
    || summary.agentTaskId !== agentTaskId
  ) {
    return undefined;
  }
  return { conversationId, placeholderMessageId, agentTaskId, summary };
}

export function conversationAgentActivityMetadata(
  message: ConversationMessageItem,
): ConversationAgentActivityPresentation | undefined {
  const turn = conversationAgentTurnMetadata(message);
  const rawTurn = message.metadata?.conversation_turn;
  if (!turn || !isRecord(rawTurn)) return undefined;
  const summary = parseConversationAgentActivitySummary(rawTurn.activity_summary);
  return summary?.agentTaskId === turn.agentTaskId ? summary : undefined;
}
