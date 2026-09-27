import type { DerivedAgentTaskArtifact } from './artifactDerivation';

/**
 * Deterministic fingerprint of one artifact's review-worthiness. Changes
 * exactly when the artifact becomes newly previewable-and-reviewable, or an
 * already-seen artifact's revision count increases (a material revision).
 */
export function artifactReviewFingerprint(artifact: DerivedAgentTaskArtifact): string {
  const revisionCount = artifact.review?.revisionCount ?? 0;
  return `${artifact.artifactId}:${artifact.lifecycle}:${revisionCount}`;
}

export function isAutoOpenEligible(artifact: DerivedAgentTaskArtifact): boolean {
  return artifact.group === 'produced'
    && artifact.artifactKind === 'file'
    && artifact.lifecycle !== 'unavailable'
    && typeof artifact.localPath === 'string'
    && artifact.localPath.startsWith('/')
    && artifact.preview.capability !== 'unsupported';
}

/** Record the initial task state without treating hydrated artifacts as new. */
export function recordArtifactReviewFingerprints(
  artifacts: DerivedAgentTaskArtifact[],
  seenFingerprints: Map<string, string>,
): void {
  for (const artifact of artifacts) {
    if (isAutoOpenEligible(artifact)) {
      seenFingerprints.set(artifact.artifactId, artifactReviewFingerprint(artifact));
    }
  }
}

/**
 * Pick the artifact (if any) whose fingerprint changed since the last time
 * this function ran for this task, and that has not been explicitly
 * dismissed at its current fingerprint. `seenFingerprints` and
 * `dismissedFingerprints` are mutated in place by the caller (they are refs
 * that persist across renders): each post-hydration artifact arrival or
 * revision change that has not been dismissed at its new fingerprint should
 * auto-open, and every fingerprint this function inspects is recorded as
 * seen so the same artifact does not re-trigger next render.
 */
export function selectArtifactForAutoOpen(
  artifacts: DerivedAgentTaskArtifact[],
  seenFingerprints: Map<string, string>,
  dismissedFingerprints: Map<string, string>,
): string | undefined {
  let selected: string | undefined;
  for (const artifact of artifacts) {
    if (!isAutoOpenEligible(artifact)) continue;
    const fingerprint = artifactReviewFingerprint(artifact);
    const previouslySeen = seenFingerprints.get(artifact.artifactId);
    seenFingerprints.set(artifact.artifactId, fingerprint);
    if (previouslySeen === fingerprint) continue;
    if (dismissedFingerprints.get(artifact.artifactId) === fingerprint) continue;
    if (!selected) selected = artifact.artifactId;
  }
  return selected;
}
