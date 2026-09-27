import { parseAgentTaskArtifact } from '../../artifacts/artifactContract';
import type {
  ResultSeverity,
  StepDetailEntry,
  TimelineEntry,
} from '../../types';

export function deriveResultSeverity(status: string | undefined, outcome: string | undefined): ResultSeverity {
  const normalizedOutcome = (outcome || '').toLowerCase();
  if (normalizedOutcome === 'partial') return 'warning';
  if (normalizedOutcome === 'completed_with_warnings') return 'success';
  if (normalizedOutcome === 'failure') return 'error';
  if (normalizedOutcome === 'success') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'completed') return 'success';
  return 'neutral';
}

export function withSelectedArtifact(detail: StepDetailEntry): StepDetailEntry {
  const { artifact: _ignoredArtifact, ...untypedDetail } = detail;
  const artifact = parseAgentTaskArtifact(detail.metadata?.artifact);
  return {
    ...untypedDetail,
    ...(artifact ? { artifact } : {}),
  };
}

export function timelineEntryToDetail(entry: TimelineEntry): StepDetailEntry | null {
  const hasDetail =
    !!entry.detail_kind ||
    !!entry.body ||
    !!entry.summary ||
    !!entry.metadata;
  if (!hasDetail) return null;

  const id = entry.id || `${entry.type}-${entry.timestamp}-${entry.content.slice(0, 24)}`;
  return withSelectedArtifact({
    id,
    type: entry.type,
    timestamp: entry.timestamp,
    content: entry.content,
    step_id: entry.step_id,
    correlation_id: entry.correlation_id || entry.step_id || id,
    detail_kind: entry.detail_kind || entry.type,
    summary: entry.summary || entry.content,
    body: entry.body || entry.content,
    metadata: entry.metadata,
    streaming: entry.streaming,
  });
}

export function detailsFromTimeline(timeline: TimelineEntry[]): StepDetailEntry[] {
  const byId = new Map<string, StepDetailEntry>();
  for (const entry of timeline) {
    const detail = timelineEntryToDetail(entry);
    if (detail) byId.set(detail.id, detail);
  }
  return Array.from(byId.values());
}
