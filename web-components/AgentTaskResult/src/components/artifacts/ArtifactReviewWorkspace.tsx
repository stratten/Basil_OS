import { useCallback, useEffect, useMemo, useState } from 'react';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';
import {
  getArtifactRevision,
  listArtifactRevisions,
  type ArtifactRevisionContent,
  type ArtifactRevisionItem,
} from '../../services/api';
import { useManagedVersionHistory } from './managedHistory/useManagedVersionHistory';
import { ManagedVersionControls, ManagedVersionRestoreError } from './managedHistory/ManagedVersionControls';
import { InlineArtifactPreview } from './InlineArtifactPreview';
import MarkdownRenderer from '../MarkdownRenderer';
import { diffLines, type DiffLine } from './diffLines';
import { DiffView } from './DiffView';
import type { ArtifactPreviewTransport } from './transport/artifactPreviewTransport';
import CrossfadeStack from '../CrossfadeStack';
import type { AgentTaskRunFocusSummary } from '../run/agentTaskRunFocus';
import { useLiveHtmlPreview } from './livePreview/useLiveHtmlPreview';
import { LiveHtmlPreviewSurface } from './livePreview/LiveHtmlPreviewSurface';
import { buildInlineStaticPreviewUrl } from '../../services/bridge';
import { getBaseUrl } from '../../services/api';
import { wsManager } from '../../services/websocket';

const TEXT_DIFF_KINDS = new Set(['markdown', 'html', 'text', 'code', 'json', 'yaml', 'xml']);

export type ArtifactReviewMode = 'render' | 'source' | 'diff';

export interface ArtifactReviewWorkspaceProps {
  agentTaskId: string;
  rootTaskId: string;
  focusedRunId: string;
  artifacts: DerivedAgentTaskArtifact[];
  activeArtifactId: string;
  onSelectArtifact: (artifactId: string) => void;
  showDocumentTabs?: boolean;
  previewTransport: ArtifactPreviewTransport;
  runs?: AgentTaskRunFocusSummary[];
}

export interface ArtifactReviewDocumentTabsProps {
  artifacts: DerivedAgentTaskArtifact[];
  activeArtifactId: string;
  onSelectArtifact: (artifactId: string) => void;
}

export function ArtifactReviewDocumentTabs({
  artifacts,
  activeArtifactId,
  onSelectArtifact,
}: ArtifactReviewDocumentTabsProps) {
  return (
    <div className="artifact-review-tabs" role="tablist" aria-label="Documents produced this turn">
      {artifacts.map(artifact => (
        <button
          key={artifact.artifactId}
          type="button"
          role="tab"
          aria-selected={artifact.artifactId === activeArtifactId}
          className={`artifact-review-tab${artifact.artifactId === activeArtifactId ? ' is-active' : ''}`}
          onClick={() => onSelectArtifact(artifact.artifactId)}
        >
          <span className="artifact-review-tab-name">{artifact.displayName}</span>
          {artifact.review && artifact.review.revisionCount > 1 && (
            <span className="artifact-review-tab-badge">v{artifact.review.revisionCount}</span>
          )}
          <span className="artifact-review-tab-tooltip" aria-hidden="true">{artifact.displayName}</span>
        </button>
      ))}
    </div>
  );
}

type ReviewSource = 'managed' | 'taskSnapshot' | 'none';

interface TaskSnapshotState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  artifactId?: string;
  canonicalPath?: string;
  errorMessage?: string;
  taskRevisions: ArtifactRevisionItem[];
  selectedContent?: string;
  compareContent?: string;
}

const EMPTY_TASK_SNAPSHOT_STATE: TaskSnapshotState = { status: 'idle', taskRevisions: [] };

function isTextReviewable(artifact: DerivedAgentTaskArtifact): boolean {
  return Boolean(
    artifact.review
    && artifact.review.kind
    && TEXT_DIFF_KINDS.has(artifact.review.kind)
  );
}

function defaultModeFor(artifact: DerivedAgentTaskArtifact): ArtifactReviewMode {
  return artifact.review?.kind === 'html' || artifact.review?.kind === 'markdown' ? 'render' : 'source';
}

export function ArtifactReviewWorkspace({
  agentTaskId,
  rootTaskId,
  focusedRunId,
  artifacts,
  activeArtifactId,
  onSelectArtifact,
  showDocumentTabs = true,
  previewTransport,
  runs,
}: ArtifactReviewWorkspaceProps) {
  const activeArtifact = artifacts.find(artifact => artifact.artifactId === activeArtifactId);
  const [mode, setMode] = useState<ArtifactReviewMode>('source');
  const [reviewSource, setReviewSource] = useState<Exclude<ReviewSource, 'none'>>('taskSnapshot');
  const [taskSnapshotState, setTaskSnapshotState] = useState<TaskSnapshotState>(EMPTY_TASK_SNAPSHOT_STATE);
  const [taskSnapshotReloadKey, setTaskSnapshotReloadKey] = useState(0);

  useEffect(() => {
    setMode(activeArtifact ? defaultModeFor(activeArtifact) : 'source');
    setReviewSource((activeArtifact?.review?.revisionCount ?? 0) > 0 ? 'taskSnapshot' : 'managed');
    setTaskSnapshotState(EMPTY_TASK_SNAPSHOT_STATE);
    setTaskSnapshotReloadKey(0);
  }, [activeArtifact?.artifactId]);

  const reviewable = activeArtifact ? isTextReviewable(activeArtifact) : false;
  const canonicalPath = activeArtifact?.localPath;
  const activeArtifactId_ = activeArtifact?.artifactId;
  const hasTaskSnapshot = (activeArtifact?.review?.revisionCount ?? 0) > 0;
  const selectedReviewSource = hasTaskSnapshot ? reviewSource : 'managed';
  const isCurrentTaskSnapshot = taskSnapshotState.artifactId === activeArtifactId_
    && taskSnapshotState.canonicalPath === canonicalPath;

  const managed = useManagedVersionHistory({
    canonicalPath: reviewable ? canonicalPath : undefined,
    enabled: reviewable && selectedReviewSource === 'managed',
    rootTaskId,
    focusedAgentTaskId: focusedRunId,
    refreshKey: activeArtifact?.review?.revisionCount,
  });

  useEffect(() => {
    if (!reviewable || selectedReviewSource !== 'taskSnapshot' || !activeArtifactId_) {
      return;
    }
    let isCurrent = true;
    setTaskSnapshotState({
      ...EMPTY_TASK_SNAPSHOT_STATE,
      status: 'loading',
      artifactId: activeArtifactId_,
      canonicalPath,
    });

    async function load() {
      try {
        const { revisions } = await listArtifactRevisions(agentTaskId, activeArtifactId_!);
        if (!isCurrent) return;
        if (revisions.length === 0) {
          setTaskSnapshotState({
            ...EMPTY_TASK_SNAPSHOT_STATE,
            status: 'error',
            artifactId: activeArtifactId_,
            canonicalPath,
            errorMessage: 'No stored revisions for this document yet.',
          });
          return;
        }
        const latest = revisions[0];
        const previous = revisions[1];
        const [selectedContent, compareContent]: [ArtifactRevisionContent, ArtifactRevisionContent | undefined] = await Promise.all([
          getArtifactRevision(agentTaskId, activeArtifactId_!, latest.revision),
          previous ? getArtifactRevision(agentTaskId, activeArtifactId_!, previous.revision) : Promise.resolve(undefined),
        ]);
        if (!isCurrent) return;
        setTaskSnapshotState({
          status: 'ready',
          artifactId: activeArtifactId_,
          canonicalPath,
          taskRevisions: revisions,
          selectedContent: selectedContent.content,
          compareContent: compareContent?.content,
        });
      } catch (error) {
        if (!isCurrent) return;
        setTaskSnapshotState({
          ...EMPTY_TASK_SNAPSHOT_STATE,
          status: 'error',
          artifactId: activeArtifactId_,
          canonicalPath,
          errorMessage: error instanceof Error ? error.message : 'Unable to load document revisions.',
        });
      }
    }

    void load();
    return () => {
      isCurrent = false;
    };
  }, [agentTaskId, activeArtifactId_, canonicalPath, reviewable, selectedReviewSource, taskSnapshotReloadKey]);

  const source: ReviewSource = !reviewable
    ? 'none'
    : selectedReviewSource;

  const status = source === 'managed'
    ? managed.state.status === 'idle' ? 'loading' : managed.state.status
    : source === 'taskSnapshot'
      ? isCurrentTaskSnapshot ? taskSnapshotState.status : 'loading'
      : 'idle';
  const errorMessage = source === 'managed' ? managed.state.errorMessage : isCurrentTaskSnapshot ? taskSnapshotState.errorMessage : undefined;
  const selectedContent = source === 'managed' ? managed.state.selectedContent : isCurrentTaskSnapshot ? taskSnapshotState.selectedContent : undefined;
  const compareContent = source === 'managed' ? managed.state.compareContent : isCurrentTaskSnapshot ? taskSnapshotState.compareContent : undefined;

  const handleRetry = () => {
    if (source === 'managed') {
      managed.retry();
    } else if (source === 'taskSnapshot') {
      setTaskSnapshotReloadKey(current => current + 1);
    }
  };

  const diff = useMemo<DiffLine[] | undefined>(() => {
    if (mode !== 'diff' || selectedContent === undefined) return undefined;
    return diffLines(compareContent ?? '', selectedContent);
  }, [mode, selectedContent, compareContent]);

  const subscribeToLiveHtmlEvents = useCallback((onEvent: () => void) => {
    if (!activeArtifactId_) return () => undefined;
    return wsManager.subscribe(event => {
      if (event.event_type !== 'agent_task_artifact') return;
      const sourceTaskId = typeof event.agent_task_id === 'string' ? event.agent_task_id : '';
      const eventRootTaskId = typeof event.root_task_id === 'string' ? event.root_task_id : '';
      const eventArtifact = event.agent_task_artifact;
      if (
        (sourceTaskId !== agentTaskId && eventRootTaskId !== agentTaskId)
        || !eventArtifact
        || typeof eventArtifact !== 'object'
        || (eventArtifact as { artifact_id?: unknown }).artifact_id !== activeArtifactId_
      ) {
        return;
      }
      onEvent();
    });
  }, [agentTaskId, activeArtifactId_]);
  const liveHtmlPreview = useLiveHtmlPreview({
    mode: 'static',
    targetUrl: canonicalPath ?? '',
    previewContentUrl: canonicalPath ? buildInlineStaticPreviewUrl(canonicalPath) : undefined,
    agentTaskId,
    artifactId: activeArtifactId_ ?? '',
    rootTaskId,
    canonicalPath,
    subscribeToArtifactEvents: subscribeToLiveHtmlEvents,
    getApiBaseUrl: getBaseUrl,
    externalManagedHistory: managed,
  });

  if (!activeArtifact) return null;

  const canDiff = reviewable && compareContent !== undefined;
  const bodyKey = [
    activeArtifact.artifactId,
    mode,
    status,
    source,
    source === 'managed' ? managed.state.selectedIndex : selectedContent?.length ?? '',
  ].join(':');

  return (
    <div className="artifact-review-workspace" aria-label="Artifact review">
      {showDocumentTabs && (
        <ArtifactReviewDocumentTabs
          artifacts={artifacts}
          activeArtifactId={activeArtifactId}
          onSelectArtifact={onSelectArtifact}
        />
      )}

      {reviewable && (
        <div className="artifact-review-controls">
          <div className="artifact-review-control-stack">
            {hasTaskSnapshot && (
              <div className="artifact-review-source-toggle" role="tablist" aria-label="Document source">
                <button
                  type="button"
                  role="tab"
                  aria-selected={source === 'taskSnapshot'}
                  className={`artifact-review-source${source === 'taskSnapshot' ? ' is-active' : ''}`}
                  onClick={() => setReviewSource('taskSnapshot')}
                >
                  Task snapshot
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={source === 'managed'}
                  className={`artifact-review-source${source === 'managed' ? ' is-active' : ''}`}
                  onClick={() => setReviewSource('managed')}
                >
                  Managed history
                </button>
              </div>
            )}
            <div className="artifact-review-mode-toggle" role="tablist" aria-label="Preview mode">
              {(['render', 'source', 'diff'] as ArtifactReviewMode[]).map(candidate => (
                <button
                  key={candidate}
                  type="button"
                  role="tab"
                  aria-selected={mode === candidate}
                  disabled={candidate === 'diff' && !canDiff}
                  className={`artifact-review-mode${mode === candidate ? ' is-active' : ''}`}
                  onClick={() => setMode(candidate)}
                  title={candidate === 'diff' && !canDiff ? 'A prior version is required to show a diff.' : undefined}
                >
                  {candidate === 'render' ? 'Render' : candidate === 'source' ? 'Source' : 'Diff'}
                </button>
              ))}
            </div>
          </div>

          {source === 'managed' && (
            <ManagedVersionControls
              state={managed.state}
              canRestore={managed.canRestore}
              runs={runs}
              onSelect={managed.selectVersion}
              onRestore={managed.restore}
            />
          )}
        </div>
      )}

      {source === 'managed' && <ManagedVersionRestoreError state={managed.state} />}

      <CrossfadeStack contentKey={bodyKey} className="artifact-review-body">
        {!reviewable ? (
          <InlineArtifactPreview
            artifact={activeArtifact}
            presentation="tray"
            transport={previewTransport}
            agentTaskId={agentTaskId}
            rootTaskId={rootTaskId}
          />
        ) : status === 'loading' ? (
          <p className="artifact-review-status" role="status">Loading document version history.</p>
        ) : status === 'error' ? (
          <div className="artifact-review-status" role="alert">
            <p>{errorMessage}</p>
            <button type="button" className="artifact-review-retry" onClick={handleRetry}>Retry</button>
          </div>
        ) : status === 'empty' ? (
          <p className="artifact-review-status" role="status">No managed document history is available.</p>
        ) : mode === 'diff' && diff ? (
          <DiffView diff={diff} label={`Diff for ${activeArtifact.displayName}`} />
        ) : mode === 'render' && activeArtifact.review?.kind === 'markdown' ? (
          <MarkdownRenderer content={selectedContent || ''} />
        ) : mode === 'render' && activeArtifact.review?.kind === 'html' ? (
          <LiveHtmlPreviewSurface
            {...liveHtmlPreview}
            displayName={activeArtifact.displayName}
            className="artifact-review-html-frame"
          />
        ) : (
          <pre className="artifact-review-source"><code>{selectedContent}</code></pre>
        )}
      </CrossfadeStack>
    </div>
  );
}
