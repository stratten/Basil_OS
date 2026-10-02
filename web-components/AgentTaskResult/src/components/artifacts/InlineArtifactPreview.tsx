import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { AgentTaskArtifactPresentation } from '../../artifacts/artifactContract';
import MarkdownRenderer from '../MarkdownRenderer';
import type { ArtifactPreviewTransport, FilePreviewPayload } from './transport/artifactPreviewTransport';
import { canOpenStaticLocalWebPreview } from './artifactPreviewEligibility';
import { presentFilePreview } from './filePreviewPresentation';
import { useNativeArtifactPreviewSlot } from './useNativeArtifactPreviewSlot';
import CrossfadeStack from '@shared/CrossfadeStack';
import { useLiveHtmlPreview } from './livePreview/useLiveHtmlPreview';
import { LiveHtmlPreviewSurface } from './livePreview/LiveHtmlPreviewSurface';
import { buildInlineStaticPreviewUrl } from '../../services/bridge';
import { getBaseUrl } from '../../services/api';
import type { AgentTaskEventSubscriber } from '../../services/websocket';

export interface InlineArtifactPreviewProps {
  artifact?: AgentTaskArtifactPresentation;
  presentation?: 'standalone' | 'tray';
  transport: ArtifactPreviewTransport;
  /** Required to render a live HTML preview instead of the raw-source fallback. */
  agentTaskId?: string;
  rootTaskId?: string;
  onOpenFile?: (path: string) => void;
  onOpenContainingFolder?: (path: string) => void;
  onOpenPreviewWindow?: (path: string) => void;
  onOpenLocalWebPreview?: (path: string) => void;
  /** Live artifact events from the host surface's own connected WebSocket. */
  subscribeToEvents: AgentTaskEventSubscriber;
}

type InlinePreviewStatus = 'empty' | 'loading' | 'ready' | 'unsupported' | 'error';

interface InlinePreviewState {
  artifact?: AgentTaskArtifactPresentation;
  requestSerial: number;
  status: InlinePreviewStatus;
  payload?: FilePreviewPayload;
  errorMessage?: string;
}

const EMPTY_STATE: InlinePreviewState = {
  requestSerial: 0,
  status: 'empty',
};

export function canRequestInlinePreview(artifact: AgentTaskArtifactPresentation): artifact is AgentTaskArtifactPresentation & { localPath: string } {
  return artifact.artifactKind === 'file'
    && artifact.lifecycle !== 'unavailable'
    && typeof artifact.localPath === 'string'
    && artifact.localPath.startsWith('/')
    && artifact.preview.capability !== 'unsupported';
}

function unsupportedMessage(artifact: AgentTaskArtifactPresentation): string {
  if (!artifact.localPath) return 'This artifact does not have a local file to preview.';
  if (artifact.artifactKind !== 'file') return 'Only files can be previewed here.';
  if (artifact.lifecycle === 'unavailable') return 'This artifact is unavailable for preview.';
  return 'This artifact is not supported by the in-app preview.';
}

function errorMessageFromUnknown(error: unknown): string {
  return error instanceof Error ? error.message : 'Unable to load file preview.';
}

export function InlineArtifactPreview({
  artifact,
  presentation: presentationMode = 'standalone',
  transport,
  agentTaskId,
  rootTaskId,
  onOpenFile,
  onOpenContainingFolder,
  onOpenPreviewWindow,
  onOpenLocalWebPreview,
  subscribeToEvents,
}: InlineArtifactPreviewProps) {
  const nextRequestSerial = useRef(0);
  const lastFetchKey = useRef<string>();
  const [retryNonce, setRetryNonce] = useState(0);
  const [state, setState] = useState<InlinePreviewState>(EMPTY_STATE);
  const activePreviewRequestId = useRef<string>();
  const activePreviewArtifactKey = useRef<string>();
  const pendingPreviewCleanup = useRef(new Set<string>());
  const artifactKey = artifact ? `${artifact.artifactId}:${artifact.localPath ?? ''}` : undefined;
  const stateMatchesArtifact = state.artifact?.artifactId === artifact?.artifactId
    && state.artifact?.localPath === artifact?.localPath;
  const renderState: InlinePreviewState = artifact && !stateMatchesArtifact
    ? { artifact, requestSerial: state.requestSerial, status: 'loading' }
    : state;

  useLayoutEffect(() => {
    if (
      activePreviewRequestId.current
      && activePreviewArtifactKey.current !== artifactKey
    ) {
      transport.clearFilePreview(activePreviewRequestId.current);
      activePreviewRequestId.current = undefined;
      activePreviewArtifactKey.current = undefined;
    }
  }, [artifactKey, transport]);

  useEffect(() => {
    const requestSerial = ++nextRequestSerial.current;
    if (!artifact) {
      lastFetchKey.current = undefined;
      setState({ requestSerial, status: 'empty' });
      return;
    }

    if (!canRequestInlinePreview(artifact)) {
      lastFetchKey.current = undefined;
      setState({
        artifact,
        requestSerial,
        status: 'unsupported',
        errorMessage: unsupportedMessage(artifact),
      });
      return;
    }

    const selectedArtifact = artifact;
    const selectedPath = selectedArtifact.localPath;
    const fetchKey = `${selectedPath}:${retryNonce}`;
    if (lastFetchKey.current === fetchKey) {
      setState(current => (
        current.artifact?.localPath === selectedPath
        && (current.status === 'ready' || current.status === 'loading')
          ? { ...current, artifact: selectedArtifact, requestSerial }
          : current
      ));
      return;
    }

    lastFetchKey.current = fetchKey;
    let isCurrent = true;
    setState({ artifact: selectedArtifact, requestSerial, status: 'loading' });
    transport.previewFile(selectedPath)
      .then(payload => {
        if (!isCurrent) return;
        setState(current => {
          if (current.requestSerial !== requestSerial) return current;
          return payload.error
            ? {
                artifact: selectedArtifact,
                requestSerial,
                status: 'error',
                payload,
                errorMessage: payload.error,
              }
            : {
                artifact: selectedArtifact,
                requestSerial,
                status: 'ready',
                payload,
              };
        });
      })
      .catch(error => {
        if (!isCurrent) return;
        setState(current => current.requestSerial === requestSerial
          ? {
              artifact: selectedArtifact,
              requestSerial,
              status: 'error',
              errorMessage: errorMessageFromUnknown(error),
            }
          : current);
      });
    return () => {
      isCurrent = false;
    };
  }, [
    artifact?.artifactId,
    artifact?.artifactKind,
    artifact?.lifecycle,
    artifact?.localPath,
    artifact?.preview.capability,
    retryNonce,
  ]);

  const previewPresentation = renderState.status === 'ready' && renderState.payload
    ? presentFilePreview(renderState.payload.kind)
    : undefined;
  const isNativePDF = previewPresentation?.renderMode === 'native_pdf';
  const nativePreviewSlotRef = useNativeArtifactPreviewSlot({
    requestId: isNativePDF ? renderState.payload?.requestId : undefined,
    enabled: isNativePDF,
    transport,
  });

  const isLiveHtmlCandidate = previewPresentation?.renderMode === 'live_html';
  const liveHtmlArtifactId = renderState.artifact?.artifactId;
  // Only feed a canonicalPath (which enables the version-history fetch
  // inside the hook) once we actually know this artifact is HTML -- other
  // artifact kinds routed through this component (markdown, source, pdf)
  // have no use for the live-preview machinery and must not trigger it.
  const liveHtmlPath = isLiveHtmlCandidate ? renderState.artifact?.localPath : undefined;
  const subscribeToLiveHtmlEvents = useCallback((onEvent: () => void) => {
    if (!agentTaskId || !liveHtmlArtifactId) return () => undefined;
    return subscribeToEvents(event => {
      if (event.event_type !== 'agent_task_artifact') return;
      const sourceTaskId = typeof event.agent_task_id === 'string' ? event.agent_task_id : '';
      const eventRootTaskId = typeof event.root_task_id === 'string' ? event.root_task_id : '';
      const eventArtifact = event.agent_task_artifact;
      if (
        (sourceTaskId !== agentTaskId && eventRootTaskId !== agentTaskId)
        || !eventArtifact
        || typeof eventArtifact !== 'object'
        || (eventArtifact as { artifact_id?: unknown }).artifact_id !== liveHtmlArtifactId
      ) {
        return;
      }
      onEvent();
    });
  }, [agentTaskId, liveHtmlArtifactId, subscribeToEvents]);
  const liveHtmlPreview = useLiveHtmlPreview({
    mode: 'static',
    targetUrl: liveHtmlPath ?? '',
    previewContentUrl: liveHtmlPath ? buildInlineStaticPreviewUrl(liveHtmlPath) : undefined,
    agentTaskId: agentTaskId ?? '',
    artifactId: liveHtmlArtifactId ?? '',
    rootTaskId,
    canonicalPath: liveHtmlPath,
    subscribeToArtifactEvents: subscribeToLiveHtmlEvents,
    getApiBaseUrl: getBaseUrl,
  });

  useEffect(() => transport.registerFilePreviewUpdateHandler(payload => {
    setState(current => (
      current.status === 'ready' && current.payload?.requestId === payload.requestId
        ? { ...current, payload, errorMessage: payload.error }
        : current
    ));
  }), [transport]);

  useEffect(() => {
    const nextRequestId = state.status === 'ready' ? state.payload?.requestId : undefined;
    const currentRequestId = activePreviewRequestId.current;
    if (currentRequestId && currentRequestId !== nextRequestId) {
      pendingPreviewCleanup.current.add(currentRequestId);
    }
    activePreviewRequestId.current = nextRequestId;
    activePreviewArtifactKey.current = nextRequestId && state.artifact
      ? `${state.artifact.artifactId}:${state.artifact.localPath ?? ''}`
      : undefined;
  }, [state.artifact, state.payload?.requestId, state.status]);

  useEffect(() => () => {
    if (activePreviewRequestId.current) transport.clearFilePreview(activePreviewRequestId.current);
    pendingPreviewCleanup.current.forEach(requestId => transport.clearFilePreview(requestId));
    pendingPreviewCleanup.current.clear();
  }, [transport]);

  const completeOutgoingPreview = useCallback(() => {
    pendingPreviewCleanup.current.forEach(requestId => transport.clearFilePreview(requestId));
    pendingPreviewCleanup.current.clear();
  }, [transport]);

  if (renderState.status === 'empty' || !renderState.artifact) return null;

  const path = renderState.artifact.localPath;
  const canOpenBrowserPreview = canOpenStaticLocalWebPreview(renderState.artifact);
  const canRenderMarkdown = previewPresentation?.renderMode === 'markdown'
    && Boolean(renderState.payload?.content);
  const canRenderLiveHtml = previewPresentation?.renderMode === 'live_html'
    && Boolean(path)
    && Boolean(agentTaskId);
  // Without an agentTaskId (e.g. a plain "open file" preview outside an
  // agent task context) the live-preview scheme URL and session plumbing
  // have nothing to key off of, so gracefully degrade to the same escaped
  // raw-source display htmlSource always used before live preview existed.
  const canRenderSource = (
    previewPresentation?.renderMode === 'source'
    || (previewPresentation?.renderMode === 'live_html' && !canRenderLiveHtml)
  ) && Boolean(renderState.payload?.content);
  const message = renderState.status === 'loading'
    ? 'Loading preview'
    : renderState.status === 'error'
      ? renderState.errorMessage || 'Unable to load file preview.'
      : renderState.status === 'unsupported'
        ? renderState.errorMessage || 'This file type is not supported by the in-app preview.'
        : 'This file type is not supported by the in-app preview.';
  const bodyKey = [
    renderState.artifact.artifactId,
    renderState.status,
    renderState.payload?.requestId ?? '',
    renderState.payload?.kind ?? '',
  ].join(':');

  return (
    <section className={`inline-artifact-preview${presentationMode === 'tray' ? ' inline-artifact-preview--tray' : ''}`} aria-labelledby={presentationMode === 'tray' ? undefined : 'inline-artifact-preview-title'}>
      {presentationMode === 'standalone' && (
        <div className="inline-artifact-preview-heading">
          <div>
            <p className="inline-artifact-preview-eyebrow">{previewPresentation?.label || 'File Preview'}</p>
            <h3 id="inline-artifact-preview-title" title={renderState.artifact.displayName}>{renderState.artifact.displayName}</h3>
          </div>
          {path && (onOpenFile || onOpenContainingFolder || onOpenPreviewWindow || (onOpenLocalWebPreview && canOpenBrowserPreview)) && (
            <div className="inline-artifact-preview-actions">
              {onOpenFile && <button type="button" onClick={() => onOpenFile(path)}>Open File</button>}
              {onOpenContainingFolder && <button type="button" onClick={() => onOpenContainingFolder(path)}>Show in Folder</button>}
              {onOpenPreviewWindow && <button type="button" onClick={() => onOpenPreviewWindow(path)}>Open Preview Window</button>}
              {onOpenLocalWebPreview && canOpenBrowserPreview && <button type="button" onClick={() => onOpenLocalWebPreview(path)}>Preview in Browser</button>}
            </div>
          )}
        </div>
      )}
      <CrossfadeStack
        contentKey={bodyKey}
        className="inline-artifact-preview-body"
        onOutgoingTransitionComplete={completeOutgoingPreview}
      >
        {canRenderMarkdown ? (
          <MarkdownRenderer content={renderState.payload?.content || ''} />
        ) : canRenderLiveHtml ? (
          <LiveHtmlPreviewSurface {...liveHtmlPreview} displayName={renderState.artifact.displayName} />
        ) : canRenderSource ? (
          <pre><code>{renderState.payload?.content}</code></pre>
        ) : isNativePDF ? (
          <div
            ref={nativePreviewSlotRef}
            className="inline-artifact-native-preview-slot"
            aria-label={`Native PDF preview for ${renderState.artifact.displayName}`}
          >
            <p>Rendering native PDF preview.</p>
          </div>
        ) : (
          <div
            className={`inline-artifact-preview-message inline-artifact-preview-message--${renderState.status}`}
            role={renderState.status === 'error' ? 'alert' : renderState.status === 'loading' ? 'status' : undefined}
          >
            <p>{message}</p>
            {renderState.status === 'error' && (
              <button type="button" onClick={() => setRetryNonce(current => current + 1)}>Retry preview</button>
            )}
          </div>
        )}
      </CrossfadeStack>
    </section>
  );
}
