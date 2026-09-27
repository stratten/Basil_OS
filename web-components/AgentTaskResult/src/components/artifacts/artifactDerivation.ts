import {
  parseAgentTaskArtifact,
  type AgentTaskArtifactPresentation,
} from '../../artifacts/artifactContract';
import type { StructuredFile, TimelineEntry } from '../../types';

export type AgentTaskArtifactGroup = 'produced' | 'retrieved' | 'ungrouped';

export interface DerivedAgentTaskArtifact extends AgentTaskArtifactPresentation {
  group: AgentTaskArtifactGroup;
}

export interface DerivedAgentTaskArtifacts {
  all: DerivedAgentTaskArtifact[];
  produced: DerivedAgentTaskArtifact[];
  retrieved: DerivedAgentTaskArtifact[];
  ungrouped: DerivedAgentTaskArtifact[];
}

const PRODUCED_OPERATIONS = new Set([
  'create',
  'copy',
  'delete',
  'move',
  'rename',
  'update',
  'write',
  'modify',
  'overwrite',
  'append',
]);
const RETRIEVED_OPERATIONS = new Set(['read', 'retrieve', 'retrieved']);
const VERIFICATION_EVIDENCE = new Set(['verified', 'failed']);

type DerivedArtifactCandidate = {
  artifact: AgentTaskArtifactPresentation;
  source: 'finalizer' | 'timeline';
};

function canonicalLocalPath(path: string | undefined): string | undefined {
  if (!path || !path.startsWith('/')) return undefined;

  const segments: string[] = [];
  for (const segment of path.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') {
      segments.pop();
      continue;
    }
    segments.push(segment);
  }
  return `/${segments.join('/')}`;
}

function artifactIdentity(artifact: AgentTaskArtifactPresentation): string {
  return canonicalLocalPath(artifact.lineage?.originPath)
    ?? canonicalLocalPath(artifact.lineage?.currentPath)
    ?? canonicalLocalPath(artifact.localPath)
    ?? `id:${artifact.artifactId}`;
}

function artifactGroup(artifact: AgentTaskArtifactPresentation): AgentTaskArtifactGroup {
  const operation = artifact.operation?.toLowerCase();
  if (operation && RETRIEVED_OPERATIONS.has(operation)) return 'retrieved';
  if (operation && PRODUCED_OPERATIONS.has(operation)) return 'produced';
  return 'ungrouped';
}

function withTimelineProvenance(
  artifact: AgentTaskArtifactPresentation,
  entry: TimelineEntry,
): AgentTaskArtifactPresentation {
  return {
    ...artifact,
    ...(artifact.sourceTimelineEntryId || typeof entry.id !== 'string' || !entry.id
      ? {}
      : { sourceTimelineEntryId: entry.id }),
    ...(artifact.sourceStepId || typeof entry.step_id !== 'string' || !entry.step_id
      ? {}
      : { sourceStepId: entry.step_id }),
  };
}

function timelineCandidate(entry: TimelineEntry): DerivedArtifactCandidate | undefined {
  const artifact = parseAgentTaskArtifact(entry.metadata?.artifact);
  return artifact ? { artifact: withTimelineProvenance(artifact, entry), source: 'timeline' } : undefined;
}

function finalizerCandidate(file: StructuredFile): DerivedArtifactCandidate | undefined {
  const embedded = parseAgentTaskArtifact(file.artifact);
  if (embedded) return { artifact: embedded, source: 'finalizer' };

  const localPath = canonicalLocalPath(file.path);
  if (!localPath || file.kind === 'directory') return undefined;

  const displayName = file.name?.trim();
  if (!displayName) return undefined;

  const lastSegment = localPath.split('/').pop();
  if (!lastSegment) return undefined;

  return {
    artifact: {
      artifactId: `legacy:${localPath}`,
      displayName,
      localPath,
      artifactKind: 'file',
      ...(file.operation ? { operation: file.operation } : {}),
      lifecycle: 'ready',
      preview: { capability: 'unknown' },
      verification: { status: 'unknown' },
    },
    source: 'finalizer',
  };
}

function mergeTimelineEvidence(
  existing: AgentTaskArtifactPresentation,
  timeline: AgentTaskArtifactPresentation,
): AgentTaskArtifactPresentation {
  const hasVerificationEvidence = VERIFICATION_EVIDENCE.has(timeline.verification.status);
  return {
    ...existing,
    ...(hasVerificationEvidence
      ? {
          lifecycle: timeline.lifecycle,
          verification: timeline.verification,
        }
      : {}),
    ...(existing.sourceTimelineEntryId || !timeline.sourceTimelineEntryId
      ? {}
      : { sourceTimelineEntryId: timeline.sourceTimelineEntryId }),
    ...(existing.sourceStepId || !timeline.sourceStepId
      ? {}
      : { sourceStepId: timeline.sourceStepId }),
    ...(timeline.review ? { review: timeline.review } : {}),
    ...(timeline.lineage
      ? {
          lineage: timeline.lineage,
          ...(timeline.localPath ? { localPath: timeline.localPath } : {}),
          displayName: timeline.displayName,
          ...(timeline.operation ? { operation: timeline.operation } : {}),
        }
      : {}),
  };
}

function addCandidate(
  artifacts: DerivedAgentTaskArtifact[],
  indexesByIdentity: Map<string, number>,
  candidate: DerivedArtifactCandidate,
): void {
  const identity = artifactIdentity(candidate.artifact);
  const existingIndex = indexesByIdentity.get(identity);
  if (existingIndex === undefined) {
    indexesByIdentity.set(identity, artifacts.length);
    artifacts.push({ ...candidate.artifact, group: artifactGroup(candidate.artifact) });
    return;
  }

  const existing = artifacts[existingIndex];
  if (candidate.source !== 'timeline') return;
  const merged = mergeTimelineEvidence(existing, candidate.artifact);
  artifacts[existingIndex] = { ...merged, group: artifactGroup(merged) };
}

export function deriveAgentTaskArtifacts(
  files: StructuredFile[],
  timeline: TimelineEntry[],
): DerivedAgentTaskArtifacts {
  const all: DerivedAgentTaskArtifact[] = [];
  const indexesByIdentity = new Map<string, number>();

  for (const file of files) {
    const candidate = finalizerCandidate(file);
    if (candidate) addCandidate(all, indexesByIdentity, candidate);
  }
  for (const entry of timeline) {
    const candidate = timelineCandidate(entry);
    if (candidate) addCandidate(all, indexesByIdentity, candidate);
  }

  return {
    all,
    produced: all.filter((artifact) => artifact.group === 'produced'),
    retrieved: all.filter((artifact) => artifact.group === 'retrieved'),
    ungrouped: all.filter((artifact) => artifact.group === 'ungrouped'),
  };
}
