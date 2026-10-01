import { useEffect, useState, type TransitionEvent } from 'react';
import { deriveAgentTaskArtifacts, type DerivedAgentTaskArtifact } from '@agent-task/components/artifacts/artifactDerivation';
import { canOpenLocalServerPreview, canOpenStaticLocalWebPreview, selectArtifactsForPreview } from '@agent-task/components/artifacts/artifactPreviewEligibility';
import { ArtifactReviewWorkspace } from '@agent-task/components/artifacts/ArtifactReviewWorkspace';
import type { ArtifactPreviewTransport } from '@agent-task/components/artifacts/transport/artifactPreviewTransport';
import {
  checkConversationArtifactPreviewAvailability,
  openConversationArtifactContainingFolder,
  openConversationArtifactFile,
  openConversationArtifactPreviewWindow,
  openConversationLocalServerPreview,
  openConversationStaticLocalWebPreview,
} from '../../services/artifactPreviewBridge';
import { getConversationAgentTaskDetail } from '../../services/api';
import NativeSymbolIcon from '../../components/NativeSymbolIcon';
import type { ConversationArtifactPreviewSelection } from './conversationArtifactPreviewState';
import { useConversationArtifactSidebarResize } from './useConversationArtifactSidebarResize';
import type { PresencePhase } from '@agent-task/app/usePresenceTransition';
import CrossfadeStack from '@agent-task/components/CrossfadeStack';
import type { WSEvent as AgentTaskWSEvent } from '@agent-task/types';
import { basilBoardWebSocket } from '../../services/websocket';

function subscribeToAgentTaskEvents(handler: (event: AgentTaskWSEvent) => void): () => void {
  return basilBoardWebSocket.subscribe((event) => {
    if (typeof event.event_type === 'string') handler(event as unknown as AgentTaskWSEvent);
  });
}

export interface ConversationArtifactPreviewSidebarProps {
  selection: ConversationArtifactPreviewSelection;
  transport: ArtifactPreviewTransport;
  onSelectArtifact: (artifactId: string) => void;
  onClose: () => void;
  presencePhase?: PresencePhase;
  onPresenceTransitionEnd?: (event: TransitionEvent<HTMLElement>) => void;
}

interface LoadState {
  status: 'loading' | 'ready' | 'error';
  artifacts: DerivedAgentTaskArtifact[];
  errorMessage?: string;
}

const LOADING_STATE: LoadState = { status: 'loading', artifacts: [] };

export default function ConversationArtifactPreviewSidebar({
  selection,
  transport,
  onSelectArtifact,
  onClose,
  presencePhase = 'present',
  onPresenceTransitionEnd,
}: ConversationArtifactPreviewSidebarProps) {
  const [state, setState] = useState<LoadState>(LOADING_STATE);
  const sidebarResize = useConversationArtifactSidebarResize();

  useEffect(() => {
    let isCurrent = true;
    setState(LOADING_STATE);

    getConversationAgentTaskDetail(selection.agentTaskId)
      .then(async (detail) => {
        if (!isCurrent) return;
        const derived = deriveAgentTaskArtifacts(detail.files, detail.execution_timeline ?? []);
        const candidatePaths = derived.produced
          .map((artifact) => artifact.localPath)
          .filter((path): path is string => typeof path === 'string' && path.startsWith('/'));
        let availablePaths = new Set<string>();
        if (candidatePaths.length > 0) {
          try {
            availablePaths = await checkConversationArtifactPreviewAvailability(candidatePaths);
          } catch {
            // Durable revisions remain previewable when the optional native availability probe fails.
          }
        }
        if (!isCurrent) return;
        const eligible = selectArtifactsForPreview(derived.produced, availablePaths);
        setState({ status: 'ready', artifacts: eligible });
      })
      .catch((error) => {
        if (!isCurrent) return;
        setState({
          status: 'error',
          artifacts: [],
          errorMessage: error instanceof Error ? error.message : 'Unable to load this task\u2019s documents.',
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [selection.agentTaskId]);

  const activeArtifactId = selection.artifactId ?? state.artifacts[0]?.artifactId;
  const activeArtifact = state.artifacts.find((artifact) => artifact.artifactId === activeArtifactId);
  const previewWindowPath = activeArtifact?.localPath;
  const canOpenStaticPreview = activeArtifact
    ? canOpenStaticLocalWebPreview(activeArtifact)
    : false;
  const canOpenServerPreview = activeArtifact
    ? canOpenLocalServerPreview(activeArtifact)
    : false;
  const selectedArtifactIsUnavailable = state.status === 'ready'
    && Boolean(selection.artifactId)
    && !activeArtifact;
  const bodyKey = `${selection.agentTaskId}:${activeArtifactId ?? ''}:${state.status}:${selectedArtifactIsUnavailable}`;

  return (
    <aside
      className={`chats-artifact-sidebar${sidebarResize.isResizing ? ' chats-artifact-sidebar--resizing' : ''}`}
      style={sidebarResize.sidebarStyle}
      aria-label="Conversation task documents"
      data-presence-phase={presencePhase}
      aria-hidden={presencePhase === 'exiting'}
      inert={presencePhase === 'exiting' ? '' : undefined}
      onTransitionEnd={onPresenceTransitionEnd}
    >
      <div
        className="chats-artifact-sidebar-resize-handle"
        role="separator"
        tabIndex={0}
        aria-label="Resize task documents"
        aria-orientation="vertical"
        aria-valuemin={320}
        aria-valuemax={sidebarResize.maximumWidth}
        aria-valuenow={sidebarResize.width}
        {...sidebarResize.resizeHandleProps}
      />
      <div className="chats-artifact-sidebar-topbar">
        {activeArtifact ? (
          <div className="chats-artifact-sidebar-document-header">
            <div className="chats-artifact-sidebar-document-title" title={activeArtifact.displayName}>
              {activeArtifact.displayName}
            </div>
            {previewWindowPath ? (
              <div className="chats-artifact-sidebar-document-actions">
                <button type="button" className="chats-artifact-sidebar-action" onClick={() => openConversationArtifactFile(previewWindowPath)} aria-label="Open File" title="Open File">
                  <NativeSymbolIcon name="openFile" />
                </button>
                <button type="button" className="chats-artifact-sidebar-action" onClick={() => openConversationArtifactContainingFolder(previewWindowPath)} aria-label="Show in Folder" title="Show in Folder">
                  <NativeSymbolIcon name="showInFolder" />
                </button>
                <button type="button" className="chats-artifact-sidebar-action" onClick={() => openConversationArtifactPreviewWindow(previewWindowPath)} aria-label="Open Preview Window" title="Open Preview Window">
                  <NativeSymbolIcon name="openPreviewWindow" />
                </button>
                {canOpenStaticPreview && <button type="button" className="chats-artifact-sidebar-action" onClick={() => openConversationStaticLocalWebPreview(previewWindowPath, selection.agentTaskId, activeArtifact.artifactId)} aria-label="Preview static page" title="Preview static page">
                  <NativeSymbolIcon name="openLocalWebPreview" />
                </button>}
                {canOpenServerPreview && <button type="button" className="chats-artifact-sidebar-action" onClick={() => openConversationLocalServerPreview(previewWindowPath, selection.agentTaskId, activeArtifact.artifactId)} aria-label="Preview with local server" title="Preview with local server">
                  <NativeSymbolIcon name="openLocalWebPreview" />
                </button>}
              </div>
            ) : null}
          </div>
        ) : (
          <span className="chats-artifact-sidebar-eyebrow">Task documents</span>
        )}
        <button type="button" className="chats-artifact-sidebar-close" onClick={onClose} aria-label="Close document preview" title="Close document preview">
          {'\u2192'}
        </button>
      </div>

      <CrossfadeStack contentKey={bodyKey} className="chats-artifact-sidebar-body">
      {state.status === 'loading' ? (
        <p className="chats-artifact-sidebar-status" role="status">Loading documents.</p>
      ) : state.status === 'error' ? (
        <p className="chats-artifact-sidebar-status" role="alert">{state.errorMessage}</p>
      ) : state.artifacts.length === 0 ? (
        <p className="chats-artifact-sidebar-status">No documents are currently available to preview.</p>
      ) : selectedArtifactIsUnavailable ? (
        <p className="chats-artifact-sidebar-status" role="alert">The selected document is no longer available to preview.</p>
      ) : activeArtifact ? (
        <ArtifactReviewWorkspace
          agentTaskId={selection.agentTaskId}
          rootTaskId={selection.agentTaskId}
          focusedRunId={selection.agentTaskId}
          artifacts={state.artifacts}
          activeArtifactId={activeArtifact.artifactId}
          onSelectArtifact={onSelectArtifact}
          previewTransport={transport}
          subscribeToEvents={subscribeToAgentTaskEvents}
        />
      ) : null}
      </CrossfadeStack>
    </aside>
  );
}
