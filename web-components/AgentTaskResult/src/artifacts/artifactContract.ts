export type AgentTaskArtifactLifecycle =
  | 'discovered'
  | 'ready'
  | 'verified'
  | 'failed'
  | 'unavailable';

export type AgentTaskArtifactPreviewCapability = 'supported' | 'unsupported' | 'unknown';

export type AgentTaskArtifactVerificationStatus =
  | 'not_applicable'
  | 'pending'
  | 'verified'
  | 'failed'
  | 'unknown';

export type AgentTaskPresentationVerificationStatus = 'pending' | 'resolved' | 'unknown';

export type AgentTaskPresentationLifecycle =
  | 'capturing'
  | 'routing'
  | 'processing'
  | 'awaiting_user_input'
  | 'waiting_user_input'
  | 'needs_clarification'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type DelegatedProviderRunStatus =
  | 'admitted'
  | 'running'
  | 'idle'
  | 'waiting_user_input'
  | 'waiting_permission'
  | 'supervision_due'
  | 'cancelling'
  | 'interrupted'
  | 'settled'
  | 'failed'
  | 'cancelled';

export type DelegatedProviderCaptureState = 'available' | 'unavailable';

export type DelegatedProviderVerificationState =
  | 'not_applicable'
  | 'pending'
  | 'verified'
  | 'verification_mismatch'
  | 'unavailable';

export interface AgentTaskArtifactPreviewHttpResponse {
  capability: AgentTaskArtifactPreviewCapability;
  kind?: string | null;
}

export interface AgentTaskArtifactVerificationHttpResponse {
  status: AgentTaskArtifactVerificationStatus;
  summary?: string | null;
}

export type AgentTaskArtifactReviewKind =
  | 'markdown'
  | 'html'
  | 'text'
  | 'code'
  | 'json'
  | 'yaml'
  | 'xml'
  | 'pdf'
  | 'unsupported';

export type AgentTaskArtifactReviewSnapshotStatus = 'available' | 'unchanged' | 'unavailable';

export interface AgentTaskArtifactReviewHttpResponse {
  revision: number | null;
  revision_count: number;
  kind?: AgentTaskArtifactReviewKind | null;
  snapshot_status: AgentTaskArtifactReviewSnapshotStatus;
  unavailable_reason?: string | null;
}

export type AgentTaskArtifactLineageState = 'current' | 'moved' | 'deleted';

export interface AgentTaskArtifactPathTransitionHttpResponse {
  operation: string;
  source_path?: string | null;
  target_path?: string | null;
  timestamp: string;
}

export interface AgentTaskArtifactLineageHttpResponse {
  origin_path: string;
  current_path?: string | null;
  state: AgentTaskArtifactLineageState;
  transitions: AgentTaskArtifactPathTransitionHttpResponse[];
}

export interface AgentTaskArtifactHttpResponse {
  artifact_id: string;
  display_name: string;
  local_path?: string | null;
  artifact_kind: 'file' | 'directory' | 'unknown';
  operation?: string | null;
  lifecycle: AgentTaskArtifactLifecycle;
  source_timeline_entry_id?: string | null;
  source_step_id?: string | null;
  preview: AgentTaskArtifactPreviewHttpResponse;
  verification: AgentTaskArtifactVerificationHttpResponse;
  review?: AgentTaskArtifactReviewHttpResponse | null;
  lineage?: AgentTaskArtifactLineageHttpResponse | null;
}

export interface AgentTaskPresentationWorkflowHttpResponse {
  total_steps?: number | null;
  completed_steps?: number | null;
}

export interface AgentTaskPresentationSummaryHttpResponse {
  agent_task_id: string;
  lifecycle: AgentTaskPresentationLifecycle;
  latest_activity?: string | null;
  workflow: AgentTaskPresentationWorkflowHttpResponse;
  artifacts: AgentTaskArtifactHttpResponse[];
  artifact_count: number;
  verification_status: AgentTaskPresentationVerificationStatus;
  requires_user_attention: boolean;
  delegated_provider_report_cards?: DelegatedProviderReportCardsHttpResponse | null;
}

export interface DelegatedProviderReportCardHttpResponse {
  delegated_agent_run_id: string;
  run_status: DelegatedProviderRunStatus;
  run_revision: number;
  capture_state: DelegatedProviderCaptureState;
  evidence_count: number;
  latest_summary?: string | null;
  verification_state: DelegatedProviderVerificationState;
}

export interface DelegatedProviderReportCardsHttpResponse {
  items: DelegatedProviderReportCardHttpResponse[];
}

export interface AgentTaskArtifactReviewPresentation {
  revision: number | null;
  revisionCount: number;
  kind?: AgentTaskArtifactReviewKind;
  snapshotStatus: AgentTaskArtifactReviewSnapshotStatus;
  unavailableReason?: string;
}

export interface AgentTaskArtifactPathTransition {
  operation: string;
  sourcePath?: string;
  targetPath?: string;
  timestamp: string;
}

export interface AgentTaskArtifactLineage {
  originPath: string;
  currentPath?: string;
  state: AgentTaskArtifactLineageState;
  transitions: AgentTaskArtifactPathTransition[];
}

export interface AgentTaskArtifactPresentation {
  artifactId: string;
  displayName: string;
  localPath?: string;
  artifactKind: 'file' | 'directory' | 'unknown';
  operation?: string;
  lifecycle: AgentTaskArtifactLifecycle;
  sourceTimelineEntryId?: string;
  sourceStepId?: string;
  preview: {
    capability: AgentTaskArtifactPreviewCapability;
    kind?: string;
  };
  verification: {
    status: AgentTaskArtifactVerificationStatus;
    summary?: string;
  };
  review?: AgentTaskArtifactReviewPresentation;
  lineage?: AgentTaskArtifactLineage;
}

export interface DelegatedProviderReportCard {
  delegatedAgentRunId: string;
  runStatus: DelegatedProviderRunStatus;
  runRevision: number;
  captureState: DelegatedProviderCaptureState;
  evidenceCount: number;
  latestSummary?: string;
  verificationState: DelegatedProviderVerificationState;
}

export interface AgentTaskPresentationSummary {
  agentTaskId: string;
  lifecycle: AgentTaskPresentationLifecycle;
  latestActivity?: string;
  workflow: {
    totalSteps?: number;
    completedSteps?: number;
  };
  artifacts: AgentTaskArtifactPresentation[];
  artifactCount: number;
  verificationStatus: AgentTaskPresentationVerificationStatus;
  requiresUserAttention: boolean;
  delegatedProviderReportCards: DelegatedProviderReportCard[];
}

type UnknownRecord = Record<string, unknown>;

const ARTIFACT_LIFECYCLES = new Set<AgentTaskArtifactLifecycle>([
  'discovered',
  'ready',
  'verified',
  'failed',
  'unavailable',
]);
const PREVIEW_CAPABILITIES = new Set<AgentTaskArtifactPreviewCapability>([
  'supported',
  'unsupported',
  'unknown',
]);
const VERIFICATION_STATUSES = new Set<AgentTaskArtifactVerificationStatus>([
  'not_applicable',
  'pending',
  'verified',
  'failed',
  'unknown',
]);
const SUMMARY_VERIFICATION_STATUSES = new Set<AgentTaskPresentationVerificationStatus>([
  'pending',
  'resolved',
  'unknown',
]);
const MAX_VERIFICATION_SUMMARY_LENGTH = 2_000;
const REVIEW_KINDS = new Set<AgentTaskArtifactReviewKind>([
  'markdown',
  'html',
  'text',
  'code',
  'json',
  'yaml',
  'xml',
  'pdf',
  'unsupported',
]);
const REVIEW_SNAPSHOT_STATUSES = new Set<AgentTaskArtifactReviewSnapshotStatus>([
  'available',
  'unchanged',
  'unavailable',
]);
const MAX_REVIEW_UNAVAILABLE_REASON_LENGTH = 160;
const ARTIFACT_LINEAGE_STATES = new Set<AgentTaskArtifactLineageState>(['current', 'moved', 'deleted']);
const MAX_ARTIFACT_LINEAGE_TRANSITIONS = 32;
const MAX_ARTIFACT_LINEAGE_OPERATION_LENGTH = 32;
const PRESENTATION_LIFECYCLES = new Set<AgentTaskPresentationLifecycle>([
  'capturing',
  'routing',
  'processing',
  'awaiting_user_input',
  'waiting_user_input',
  'needs_clarification',
  'completed',
  'failed',
  'cancelled',
]);
const DELEGATED_PROVIDER_RUN_STATUSES = new Set<DelegatedProviderRunStatus>([
  'admitted',
  'running',
  'idle',
  'waiting_user_input',
  'waiting_permission',
  'supervision_due',
  'cancelling',
  'interrupted',
  'settled',
  'failed',
  'cancelled',
]);
const DELEGATED_PROVIDER_CAPTURE_STATES = new Set<DelegatedProviderCaptureState>([
  'available',
  'unavailable',
]);
const DELEGATED_PROVIDER_VERIFICATION_STATES = new Set<DelegatedProviderVerificationState>([
  'not_applicable',
  'pending',
  'verified',
  'verification_mismatch',
  'unavailable',
]);
const MAX_DELEGATED_PROVIDER_SUMMARY_LENGTH = 160;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function isOptionalText(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || typeof value === 'string' && value.trim().length > 0;
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function parsePreview(value: unknown): AgentTaskArtifactPresentation['preview'] | undefined {
  if (!isRecord(value) || !PREVIEW_CAPABILITIES.has(value.capability as AgentTaskArtifactPreviewCapability)) {
    return undefined;
  }
  if (!isOptionalText(value.kind)) return undefined;
  return {
    capability: value.capability as AgentTaskArtifactPreviewCapability,
    ...(typeof value.kind === 'string' ? { kind: value.kind } : {}),
  };
}

function parseVerification(value: unknown): AgentTaskArtifactPresentation['verification'] | undefined {
  if (!isRecord(value) || !VERIFICATION_STATUSES.has(value.status as AgentTaskArtifactVerificationStatus)) {
    return undefined;
  }
  if (
    !isOptionalText(value.summary) ||
    typeof value.summary === 'string' && value.summary.length > MAX_VERIFICATION_SUMMARY_LENGTH
  ) {
    return undefined;
  }
  return {
    status: value.status as AgentTaskArtifactVerificationStatus,
    ...(typeof value.summary === 'string' ? { summary: value.summary } : {}),
  };
}

function parseArtifactReview(value: unknown): AgentTaskArtifactReviewPresentation | undefined {
  if (value === null || value === undefined) return undefined;
  if (!isRecord(value)) return undefined;
  const revision = value.revision;
  if (revision !== null && !isNonNegativeSafeInteger(revision)) return undefined;
  if (revision !== null && (revision as number) < 1) return undefined;
  if (!isNonNegativeSafeInteger(value.revision_count)) return undefined;
  if (value.kind !== null && value.kind !== undefined && !REVIEW_KINDS.has(value.kind as AgentTaskArtifactReviewKind)) {
    return undefined;
  }
  if (!REVIEW_SNAPSHOT_STATUSES.has(value.snapshot_status as AgentTaskArtifactReviewSnapshotStatus)) {
    return undefined;
  }
  if (
    !isOptionalText(value.unavailable_reason)
    || typeof value.unavailable_reason === 'string' && value.unavailable_reason.length > MAX_REVIEW_UNAVAILABLE_REASON_LENGTH
  ) {
    return undefined;
  }
  return {
    revision: (revision as number | null) ?? null,
    revisionCount: value.revision_count as number,
    ...(typeof value.kind === 'string' ? { kind: value.kind as AgentTaskArtifactReviewKind } : {}),
    snapshotStatus: value.snapshot_status as AgentTaskArtifactReviewSnapshotStatus,
    ...(typeof value.unavailable_reason === 'string' ? { unavailableReason: value.unavailable_reason } : {}),
  };
}

function parseArtifactLineage(value: unknown): AgentTaskArtifactLineage | undefined {
  if (value === null || value === undefined) return undefined;
  if (!isRecord(value)) return undefined;
  const originPath = value.origin_path;
  const currentPath = value.current_path;
  const transitions = value.transitions;
  if (
    typeof originPath !== 'string'
    || !originPath.startsWith('/')
    || !ARTIFACT_LINEAGE_STATES.has(value.state as AgentTaskArtifactLineageState)
    || (currentPath !== null && currentPath !== undefined && (typeof currentPath !== 'string' || !currentPath.startsWith('/')))
    || !Array.isArray(transitions)
    || transitions.length > MAX_ARTIFACT_LINEAGE_TRANSITIONS
  ) {
    return undefined;
  }
  if (value.state === 'deleted' ? currentPath !== null && currentPath !== undefined : typeof currentPath !== 'string') {
    return undefined;
  }
  const parsedTransitions: AgentTaskArtifactPathTransition[] = [];
  for (const transition of transitions) {
    if (
      !isRecord(transition)
      || !requiredText(transition.operation)
      || (transition.operation as string).length > MAX_ARTIFACT_LINEAGE_OPERATION_LENGTH
      || typeof transition.timestamp !== 'string'
      || !transition.timestamp.trim()
      || (transition.source_path !== null && transition.source_path !== undefined && (typeof transition.source_path !== 'string' || !transition.source_path.startsWith('/')))
      || (transition.target_path !== null && transition.target_path !== undefined && (typeof transition.target_path !== 'string' || !transition.target_path.startsWith('/')))
    ) {
      return undefined;
    }
    parsedTransitions.push({
      operation: transition.operation as string,
      timestamp: transition.timestamp,
      ...(typeof transition.source_path === 'string' ? { sourcePath: transition.source_path } : {}),
      ...(typeof transition.target_path === 'string' ? { targetPath: transition.target_path } : {}),
    });
  }
  return {
    originPath,
    state: value.state as AgentTaskArtifactLineageState,
    transitions: parsedTransitions,
    ...(typeof currentPath === 'string' ? { currentPath } : {}),
  };
}

export function parseAgentTaskArtifact(value: unknown): AgentTaskArtifactPresentation | undefined {
  if (!isRecord(value)) return undefined;

  const artifactId = requiredText(value.artifact_id);
  const displayName = requiredText(value.display_name);
  const localPath = value.local_path;
  const preview = parsePreview(value.preview);
  const verification = parseVerification(value.verification);
  const lineage = parseArtifactLineage(value.lineage);
  if (!artifactId || !displayName || !ARTIFACT_LIFECYCLES.has(value.lifecycle as AgentTaskArtifactLifecycle)) {
    return undefined;
  }
  if (value.review !== null && value.review !== undefined && !parseArtifactReview(value.review)) {
    return undefined;
  }
  if (value.lineage !== null && value.lineage !== undefined && !lineage) return undefined;
  if (value.artifact_kind !== 'file' && value.artifact_kind !== 'directory' && value.artifact_kind !== 'unknown') {
    return undefined;
  }
  if (localPath !== null && localPath !== undefined && (typeof localPath !== 'string' || !localPath.trim() || !localPath.startsWith('/'))) {
    return undefined;
  }
  if (!isOptionalText(value.operation) || !isOptionalText(value.source_timeline_entry_id) || !isOptionalText(value.source_step_id)) {
    return undefined;
  }
  if (!preview || !verification) return undefined;

  return {
    artifactId,
    displayName,
    ...(typeof localPath === 'string' ? { localPath } : {}),
    artifactKind: value.artifact_kind,
    ...(typeof value.operation === 'string' ? { operation: value.operation } : {}),
    lifecycle: value.lifecycle as AgentTaskArtifactLifecycle,
    ...(typeof value.source_timeline_entry_id === 'string' ? { sourceTimelineEntryId: value.source_timeline_entry_id } : {}),
    ...(typeof value.source_step_id === 'string' ? { sourceStepId: value.source_step_id } : {}),
    preview,
    verification,
    ...(value.review !== null && value.review !== undefined ? { review: parseArtifactReview(value.review) } : {}),
    ...(lineage ? { lineage } : {}),
  };
}

export function parseDelegatedProviderReportCard(value: unknown): DelegatedProviderReportCard | undefined {
  if (!isRecord(value)) return undefined;
  const delegatedAgentRunId = requiredText(value.delegated_agent_run_id);
  const latestSummary = value.latest_summary;
  if (
    !delegatedAgentRunId
    || !DELEGATED_PROVIDER_RUN_STATUSES.has(value.run_status as DelegatedProviderRunStatus)
    || !isNonNegativeSafeInteger(value.run_revision)
    || !DELEGATED_PROVIDER_CAPTURE_STATES.has(value.capture_state as DelegatedProviderCaptureState)
    || !isNonNegativeSafeInteger(value.evidence_count)
    || !DELEGATED_PROVIDER_VERIFICATION_STATES.has(value.verification_state as DelegatedProviderVerificationState)
    || !isOptionalText(latestSummary)
    || typeof latestSummary === 'string' && latestSummary.length > MAX_DELEGATED_PROVIDER_SUMMARY_LENGTH
  ) {
    return undefined;
  }
  return {
    delegatedAgentRunId,
    runStatus: value.run_status as DelegatedProviderRunStatus,
    runRevision: value.run_revision,
    captureState: value.capture_state as DelegatedProviderCaptureState,
    evidenceCount: value.evidence_count,
    ...(typeof latestSummary === 'string' ? { latestSummary } : {}),
    verificationState: value.verification_state as DelegatedProviderVerificationState,
  };
}

export function parseDelegatedProviderReportCards(value: unknown): DelegatedProviderReportCard[] | undefined {
  if (!isRecord(value) || !Array.isArray(value.items)) return undefined;
  const seenRunIds = new Set<string>();
  const cards: DelegatedProviderReportCard[] = [];
  for (const item of value.items) {
    const card = parseDelegatedProviderReportCard(item);
    if (!card || seenRunIds.has(card.delegatedAgentRunId)) return undefined;
    seenRunIds.add(card.delegatedAgentRunId);
    cards.push(card);
  }
  return cards;
}

export function parseDelegatedProviderReportCardsForParent(
  parentAgentTaskId: string,
  value: unknown,
): DelegatedProviderReportCard[] | undefined {
  if (!isRecord(value) || requiredText(value.parent_agent_task_id) !== parentAgentTaskId) return undefined;
  return parseDelegatedProviderReportCards({ items: value.items });
}

function parseSummaryDelegatedProviderReportCards(value: UnknownRecord): DelegatedProviderReportCard[] | undefined {
  if (value.delegated_provider_report_cards === undefined || value.delegated_provider_report_cards === null) {
    return [];
  }
  return parseDelegatedProviderReportCards(value.delegated_provider_report_cards);
}

export function parseAgentTaskPresentationSummary(value: unknown): AgentTaskPresentationSummary | undefined {
  if (!isRecord(value) || !isRecord(value.workflow) || !Array.isArray(value.artifacts)) return undefined;

  const agentTaskId = requiredText(value.agent_task_id);
  const latestActivity = value.latest_activity;
  const delegatedProviderReportCards = parseSummaryDelegatedProviderReportCards(value);
  if (!agentTaskId || !PRESENTATION_LIFECYCLES.has(value.lifecycle as AgentTaskPresentationLifecycle)) {
    return undefined;
  }
  if (!isOptionalText(latestActivity) || typeof latestActivity === 'string' && latestActivity.length > 160) {
    return undefined;
  }
  if (!SUMMARY_VERIFICATION_STATUSES.has(value.verification_status as AgentTaskPresentationVerificationStatus)) {
    return undefined;
  }
  if (
    typeof value.requires_user_attention !== 'boolean'
    || value.artifacts.length > 6
    || !delegatedProviderReportCards
  ) {
    return undefined;
  }

  const totalSteps = value.workflow.total_steps;
  const completedSteps = value.workflow.completed_steps;
  if (totalSteps !== null && totalSteps !== undefined && !isNonNegativeSafeInteger(totalSteps)) return undefined;
  if (completedSteps !== null && completedSteps !== undefined && !isNonNegativeSafeInteger(completedSteps)) return undefined;

  const artifacts: AgentTaskArtifactPresentation[] = [];
  for (const item of value.artifacts) {
    const parsed = parseAgentTaskArtifact(item);
    if (!parsed) return undefined;
    artifacts.push(parsed);
  }
  if (!isNonNegativeSafeInteger(value.artifact_count) || value.artifact_count < artifacts.length) return undefined;

  return {
    agentTaskId,
    lifecycle: value.lifecycle as AgentTaskPresentationLifecycle,
    ...(typeof latestActivity === 'string' ? { latestActivity } : {}),
    workflow: {
      ...(typeof totalSteps === 'number' ? { totalSteps } : {}),
      ...(typeof completedSteps === 'number' ? { completedSteps } : {}),
    },
    artifacts,
    artifactCount: value.artifact_count,
    verificationStatus: value.verification_status as AgentTaskPresentationVerificationStatus,
    requiresUserAttention: value.requires_user_attention,
    delegatedProviderReportCards,
  };
}

export function parseAgentTaskPresentationSummaryForTask(
  agentTaskId: string,
  value: unknown,
): AgentTaskPresentationSummary | undefined {
  const summary = parseAgentTaskPresentationSummary(value);
  return summary?.agentTaskId === agentTaskId ? summary : undefined;
}
