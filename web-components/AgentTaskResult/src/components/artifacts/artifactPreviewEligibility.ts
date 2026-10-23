import type { AgentTaskArtifactPresentation } from '../../artifacts/artifactContract';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';

const MANAGED_HISTORY_TEXT_KINDS = new Set(['markdown', 'html', 'text', 'code', 'json', 'yaml', 'xml']);

export function hasStoredArtifactRevision(artifact: AgentTaskArtifactPresentation): boolean {
  return (artifact.review?.revisionCount ?? 0) > 0;
}

export function hasCurrentArtifactFile<T extends AgentTaskArtifactPresentation>(
  artifact: T,
): artifact is T & { localPath: string } {
  return artifact.artifactKind === 'file'
    && artifact.lifecycle !== 'unavailable'
    && artifact.lineage?.state !== 'deleted'
    && typeof artifact.localPath === 'string'
    && artifact.localPath.startsWith('/');
}

export function canProbeLiveArtifactPreview<T extends AgentTaskArtifactPresentation>(
  artifact: T,
): artifact is T & { localPath: string } {
  return hasCurrentArtifactFile(artifact)
    && artifact.preview.capability !== 'unsupported';
}

export function canOpenStaticLocalWebPreview<T extends AgentTaskArtifactPresentation>(
  artifact: T,
): artifact is T & { localPath: string } {
  return hasCurrentArtifactFile(artifact)
    && /\.html?$/i.test(artifact.localPath);
}

export function canOpenLocalServerPreview<T extends AgentTaskArtifactPresentation>(
  artifact: T,
): artifact is T & { localPath: string } {
  return hasCurrentArtifactFile(artifact)
    && /\.html?$/i.test(artifact.localPath);
}

export function canReviewManagedHistoryArtifact(
  artifact: DerivedAgentTaskArtifact,
): artifact is DerivedAgentTaskArtifact & { localPath: string } {
  return artifact.artifactKind === 'file'
    && typeof artifact.localPath === 'string'
    && artifact.localPath.startsWith('/')
    && typeof artifact.review?.kind === 'string'
    && MANAGED_HISTORY_TEXT_KINDS.has(artifact.review.kind);
}

export function selectArtifactsForPreview(
  artifacts: DerivedAgentTaskArtifact[],
  availableLocalPaths: ReadonlySet<string>,
): DerivedAgentTaskArtifact[] {
  return artifacts.filter(artifact => (
    hasStoredArtifactRevision(artifact)
    || canReviewManagedHistoryArtifact(artifact)
    || (canProbeLiveArtifactPreview(artifact) && availableLocalPaths.has(artifact.localPath))
  ));
}
