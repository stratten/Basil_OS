import {
  parseAgentTaskArtifact,
  type AgentTaskArtifactPresentation,
} from '../../artifacts/artifactContract';
import type { TimelineEntry, WSEvent } from '../../types';

type UnknownRecord = Record<string, unknown>;

const DIRECT_ARTIFACT_ID = /^file-[0-9a-f]{24}$/;
const MAX_VERIFICATION_SUMMARY_LENGTH = 2_000;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonEmptyText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function isDirectTextWriteArtifact(
  value: unknown,
): value is AgentTaskArtifactPresentation {
  const artifact = parseAgentTaskArtifact(value);
  if (!artifact) return false;
  return (
    DIRECT_ARTIFACT_ID.test(artifact.artifactId)
    && artifact.localPath?.startsWith('/') === true
    && artifact.artifactKind === 'file'
    && (artifact.operation === 'create' || artifact.operation === 'modify')
    && (artifact.lifecycle === 'verified' || artifact.lifecycle === 'failed')
    && artifact.preview.capability === 'unknown'
    && artifact.verification.status === artifact.lifecycle
    && typeof artifact.verification.summary === 'string'
    && artifact.verification.summary.trim().length > 0
    && artifact.verification.summary.length <= MAX_VERIFICATION_SUMMARY_LENGTH
    && typeof artifact.sourceTimelineEntryId === 'string'
    && artifact.sourceTimelineEntryId === `artifact_${artifact.artifactId}`
    && typeof artifact.sourceStepId === 'string'
    && artifact.sourceStepId.trim().length > 0
  );
}

function selectedArtifactMetadata(
  artifact: AgentTaskArtifactPresentation,
): UnknownRecord {
  return {
    artifact_id: artifact.artifactId,
    display_name: artifact.displayName,
    local_path: artifact.localPath,
    artifact_kind: 'file',
    operation: artifact.operation,
    lifecycle: artifact.lifecycle,
    source_timeline_entry_id: artifact.sourceTimelineEntryId,
    source_step_id: artifact.sourceStepId,
    preview: { capability: 'unknown' },
    verification: {
      status: artifact.verification.status,
      summary: artifact.verification.summary,
    },
  };
}

function sameArtifact(
  left: AgentTaskArtifactPresentation,
  right: AgentTaskArtifactPresentation,
): boolean {
  return (
    left.artifactId === right.artifactId
    && left.displayName === right.displayName
    && left.localPath === right.localPath
    && left.artifactKind === right.artifactKind
    && left.operation === right.operation
    && left.lifecycle === right.lifecycle
    && left.sourceTimelineEntryId === right.sourceTimelineEntryId
    && left.sourceStepId === right.sourceStepId
    && left.preview.capability === right.preview.capability
    && left.verification.status === right.verification.status
    && left.verification.summary === right.verification.summary
  );
}

function artifactTimelineEntryFromRecord(value: unknown): TimelineEntry | undefined {
  if (!isRecord(value) || !isRecord(value.metadata)) return undefined;
  const artifact = parseAgentTaskArtifact(value.metadata.artifact);
  const timestamp = nonEmptyText(value.timestamp);
  if (!isDirectTextWriteArtifact(value.metadata.artifact) || !artifact || !timestamp) return undefined;
  if (
    value.id !== artifact.sourceTimelineEntryId
    || value.type !== 'artifact'
    || value.detail_kind !== 'artifact'
    || value.metadata.event_type !== 'agent_task_artifact'
    || value.metadata.raw_detail !== true
  ) {
    return undefined;
  }

  const lifecycleTitle = artifact.lifecycle[0].toUpperCase() + artifact.lifecycle.slice(1);
  const title = `${lifecycleTitle} local file: ${artifact.displayName}`;
  return {
    id: artifact.sourceTimelineEntryId,
    type: 'artifact',
    timestamp,
    content: title,
    step_id: artifact.sourceStepId,
    correlation_id: artifact.sourceStepId,
    detail_kind: 'artifact',
    summary: title,
    body: artifact.verification.summary,
    metadata: {
      event_type: 'agent_task_artifact',
      raw_detail: true,
      artifact: selectedArtifactMetadata(artifact),
    },
    streaming: false,
  };
}

export function parseAgentTaskArtifactEvent(event: WSEvent): TimelineEntry | undefined {
  if (event.event_type !== 'agent_task_artifact') return undefined;
  const topLevelArtifact = parseAgentTaskArtifact(event.agent_task_artifact);
  const timelineEntry = artifactTimelineEntryFromRecord(event.timeline_entry);
  const timelineArtifact = timelineEntry
    ? parseAgentTaskArtifact(timelineEntry.metadata?.artifact)
    : undefined;
  if (
    !isDirectTextWriteArtifact(event.agent_task_artifact)
    || !topLevelArtifact
    || !timelineArtifact
    || !sameArtifact(topLevelArtifact, timelineArtifact)
  ) {
    return undefined;
  }
  return timelineEntry;
}

export function parsePersistedAgentTaskArtifactEntry(
  value: unknown,
): TimelineEntry | undefined {
  return artifactTimelineEntryFromRecord(value);
}

export function reconcileDurableArtifactEntries(
  liveTimeline: TimelineEntry[],
  durableTimeline: TimelineEntry[],
): TimelineEntry[] {
  const durableArtifacts = durableTimeline
    .map(parsePersistedAgentTaskArtifactEntry)
    .filter((entry): entry is TimelineEntry => entry !== undefined);
  if (durableArtifacts.length === 0) return liveTimeline;

  const reconciled = [...liveTimeline];
  for (const durableEntry of durableArtifacts) {
    const existingIndex = reconciled.findIndex(entry => entry.id === durableEntry.id);
    if (existingIndex >= 0) {
      reconciled[existingIndex] = durableEntry;
    } else {
      reconciled.push(durableEntry);
    }
  }
  return reconciled;
}
