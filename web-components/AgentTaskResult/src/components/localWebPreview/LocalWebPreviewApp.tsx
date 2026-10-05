import { useEffect, useMemo, useRef, useState } from 'react';
import NativeSymbolIcon from '../../../../shared/NativeSymbolIcon';
import { createLocalWebPreviewTransport, type LocalWebPreviewSessionDTO } from '../artifacts/transport/localWebPreviewTransport';
import { processAgentTask, setBaseUrl } from '../../services/api';
import { WebSocketManager } from '../../services/websocket';
import type {
  LocalWebPreviewInitMessage,
  LocalWebPreviewValidationServerPayload,
} from './localWebPreviewBridge';
import {
  captureScreenshot,
  closeLocalWebPreviewWindow,
  minimizeLocalWebPreviewWindow,
  notifyLocalPreviewServerSessionDenied,
  notifyLocalPreviewServerSessionStarted,
  notifyLocalWebPreviewWindowWillClose,
  openExternalUrl,
  readCurrentPreviewUrl,
  registerConsoleEvidenceHandler,
  registerLocalWebPreviewInitHandler,
  registerLocalWebPreviewValidationFeedbackHandler,
  registerLocalWebPreviewValidationServerHandler,
  reportLocalWebPreviewChromeHeight,
  requestConsoleEvidence,
} from './localWebPreviewBridge';
import { useManagedVersionHistory } from '../artifacts/managedHistory/useManagedVersionHistory';
import { ManagedVersionControls, ManagedVersionRestoreError } from '../artifacts/managedHistory/ManagedVersionControls';
import { diffLines, type DiffLine } from '../artifacts/diffLines';
import { LiveHtmlPreviewHistoryToggle, LiveHtmlPreviewSurface, type LiveHtmlPreviewSurfaceProps } from '../artifacts/livePreview/LiveHtmlPreviewSurface';

const MAX_FEEDBACK_CHARS = 4_000;
const DEFAULT_LOCAL_SERVER_PORT = 4173;
const SESSION_POLL_INTERVAL_MS = 1_000;
const VALIDATION_SERVER_COMMAND = 'python3';
const VALIDATION_SERVER_ARGS = ['server.py', '--host', '127.0.0.1', '--port', '43123'];
const VALIDATION_SERVER_PORT = 43123;

type PreviewStatus = 'connecting' | 'ready' | 'stopped' | 'error' | 'unsupported';
type HistoricalViewMode = 'render' | 'diff';

interface PreviewState {
  init?: LocalWebPreviewInitMessage;
  status: PreviewStatus;
  errorMessage?: string;
  consoleEvidence?: string;
}

function applyPreviewTheme(config: LocalWebPreviewInitMessage) {
  const root = document.documentElement;
  if (config.theme) {
    root.style.setProperty('--background-primary', config.theme.backgroundPrimary);
    root.style.setProperty('--primary', config.theme.primary);
    root.style.setProperty('--secondary', config.theme.secondary);
    root.style.setProperty('--text-primary', config.theme.textPrimary);
  }
  if (config.fonts) {
    root.style.setProperty('--font-family-light', config.fonts.fontFamily);
    root.style.setProperty('--font-family-medium', config.fonts.fontFamilyMedium);
    root.style.setProperty('--font-family-bold', config.fonts.fontFamilyBold);
  }
}

function statusLabel(status: PreviewStatus): string {
  switch (status) {
    case 'connecting': return 'Connecting';
    case 'ready': return 'Ready';
    case 'stopped': return 'Server stopped';
    case 'unsupported': return 'Unsupported';
    default: return 'Connection error';
  }
}

function previewWorkingDirectory(targetUrl: string): string {
  try {
    const path = decodeURIComponent(new URL(targetUrl).pathname);
    const lastSlash = path.lastIndexOf('/');
    return lastSlash > 0 ? path.slice(0, lastSlash) : path;
  } catch {
    return '';
  }
}

function previewUrlWithRevision(url: string, revision: number): string {
  try {
    const parsed = new URL(url);
    parsed.searchParams.set('basilPreviewRevision', String(revision));
    return parsed.toString();
  } catch {
    return url;
  }
}

export default function LocalWebPreviewApp() {
  const [state, setState] = useState<PreviewState>({ status: 'connecting' });
  const [feedbackText, setFeedbackText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string>();
  const [serverCommand, setServerCommand] = useState('');
  const [serverArgs, setServerArgs] = useState('');
  const [serverCwd, setServerCwd] = useState('');
  const [serverPort, setServerPort] = useState(DEFAULT_LOCAL_SERVER_PORT);
  const [isStartingServer, setIsStartingServer] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [lastUpdateMessage, setLastUpdateMessage] = useState('');
  const [historicalViewMode, setHistoricalViewMode] = useState<HistoricalViewMode>('render');
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const headerRef = useRef<HTMLDivElement>(null);
  const previewFrameRef = useRef<HTMLIFrameElement>(null);
  const consoleEvidenceRef = useRef('');
  const initRef = useRef<LocalWebPreviewInitMessage>();
  const previousHeadChangeId = useRef<string | undefined>(undefined);
  const validationFeedbackHandlerRef = useRef<(text: string) => void>(() => undefined);
  const validationServerHandlerRef = useRef<(payload: LocalWebPreviewValidationServerPayload) => void>(() => undefined);
  const [session, setSession] = useState<LocalWebPreviewSessionDTO>();
  const previewWebSocket = useMemo(() => new WebSocketManager(), [state.init?.wsUrl]);
  const transport = useMemo(() => createLocalWebPreviewTransport(() => {
    const port = state.init?.port;
    return typeof port === 'number' ? `http://localhost:${port}` : '';
  }), [state.init?.port]);

  const managed = useManagedVersionHistory({
    canonicalPath: state.init?.canonicalPath,
    enabled: Boolean(state.init?.canonicalPath),
    rootTaskId: state.init?.rootTaskId,
    focusedAgentTaskId: state.init?.agentTaskId,
    refreshKey: historyRefreshKey,
  });
  const hasVersionHistory = managed.state.versions.length > 0;
  const isHistorical = hasVersionHistory && managed.state.selectedIndex !== 0;
  const selectedVersionIsLoading = hasVersionHistory && managed.state.status === 'loading';
  const selectedVersionLoadFailed = hasVersionHistory && managed.state.status === 'error';
  const initialHistoryLoadFailed = !hasVersionHistory && managed.state.status === 'error';
  const canDiffHistorical = managed.state.compareContent !== undefined;

  const historicalDiff = useMemo<DiffLine[] | undefined>(() => {
    if (!isHistorical || historicalViewMode !== 'diff' || !canDiffHistorical) return undefined;
    return diffLines(managed.state.compareContent ?? '', managed.state.selectedContent ?? '');
  }, [isHistorical, historicalViewMode, canDiffHistorical, managed.state.compareContent, managed.state.selectedContent]);

  useEffect(() => {
    if (!isHistorical) setHistoricalViewMode('render');
  }, [isHistorical]);

  // After a successful restore the hook resets to index 0 pointing at the
  // newly-recorded head version. Detect that head-id change and reuse the
  // existing cache-busting revision counter (the same mechanism the
  // websocket-driven auto-refresh already uses) to force the live iframe to
  // reload the now-restored disk content.
  useEffect(() => {
    const headId = managed.state.versions[0]?.id;
    if (headId && previousHeadChangeId.current && headId !== previousHeadChangeId.current) {
      setPreviewRevision(current => current + 1);
      setLastUpdateMessage('Preview updated');
    }
    previousHeadChangeId.current = headId;
  }, [managed.state.versions]);

  useEffect(() => {
    const unregisterInit = registerLocalWebPreviewInitHandler((config) => {
      applyPreviewTheme(config);
      initRef.current = config;
      consoleEvidenceRef.current = '';
      if (typeof config.port === 'number') {
        setBaseUrl(config.port);
      }
      setServerCwd(previewWorkingDirectory(config.targetUrl));
      setPreviewRevision(0);
      setLastUpdateMessage('');
      setSession(undefined);
      const nextStatus: PreviewStatus = config.mode === 'devServer' && !config.sessionId
        ? 'unsupported'
        : 'connecting';
      setState({ init: config, status: nextStatus });
    });
    const unregisterConsole = registerConsoleEvidenceHandler((payload) => {
      consoleEvidenceRef.current = payload.text;
      setState(current => ({ ...current, consoleEvidence: payload.text }));
    });
    const unregisterValidationFeedback = registerLocalWebPreviewValidationFeedbackHandler((payload) => {
      validationFeedbackHandlerRef.current(payload.text);
    });
    const unregisterValidationServer = registerLocalWebPreviewValidationServerHandler((payload) => {
      validationServerHandlerRef.current(payload);
    });
    return () => {
      unregisterInit();
      unregisterConsole();
      unregisterValidationFeedback();
      unregisterValidationServer();
    };
  }, []);

  useEffect(() => {
    if (!headerRef.current) return;
    const observer = new ResizeObserver(() => {
      if (headerRef.current) {
        reportLocalWebPreviewChromeHeight(headerRef.current.getBoundingClientRect().height);
      }
    });
    observer.observe(headerRef.current);
    reportLocalWebPreviewChromeHeight(headerRef.current.getBoundingClientRect().height);
    return () => observer.disconnect();
  }, [state.init]);

  useEffect(() => {
    if (state.init?.mode === 'devServer' && !state.init.sessionId) {
      setState(current => ({ ...current, status: 'unsupported', errorMessage: 'No preview server session is available.' }));
    }
  }, [state.init]);

  useEffect(() => {
    const init = state.init;
    if (!init || init.mode !== 'devServer' || !init.sessionId) return;
    let isCurrent = true;
    const refreshSession = async () => {
      try {
        const polledSession = await transport.getSession({
          agentTaskId: init.agentTaskId,
          artifactId: init.artifactId,
          sessionId: init.sessionId!,
        });
        if (!isCurrent) return;
        setSession(polledSession);
        if (polledSession.status === 'running') return;
        setState(current => ({
          ...current,
          status: polledSession.status === 'stopped' ? 'stopped' : polledSession.status === 'denied' ? 'unsupported' : 'error',
          errorMessage: polledSession.lastError ?? (polledSession.status === 'stopped' ? 'The local preview server stopped.' : 'The local preview server is unavailable.'),
        }));
      } catch (error) {
        if (!isCurrent) return;
        setSession(undefined);
        setState(current => ({
          ...current,
          status: 'error',
          errorMessage: error instanceof Error ? error.message : 'Unable to check local preview server status.',
        }));
      }
    };
    void refreshSession();
    const intervalId = window.setInterval(() => void refreshSession(), SESSION_POLL_INTERVAL_MS);
    return () => {
      isCurrent = false;
      window.clearInterval(intervalId);
    };
  }, [state.init, transport]);

  useEffect(() => {
    const init = state.init;
    if (!init?.wsUrl || !init.agentTaskId || !init.artifactId) return;
    let hasConnected = false;
    const refreshPreview = () => {
      setLastUpdateMessage('Preview updated');
      setPreviewRevision(current => current + 1);
      setHistoryRefreshKey(current => current + 1);
    };
    const unsubscribeEvent = previewWebSocket.subscribe(event => {
      if (event.event_type !== 'agent_task_artifact') return;
      const sourceTaskId = typeof event.agent_task_id === 'string' ? event.agent_task_id : '';
      const rootTaskId = typeof event.root_task_id === 'string' ? event.root_task_id : '';
      const artifact = event.agent_task_artifact;
      if (
        (sourceTaskId !== init.agentTaskId && rootTaskId !== init.agentTaskId)
        || !artifact
        || typeof artifact !== 'object'
        || (artifact as { artifact_id?: unknown }).artifact_id !== init.artifactId
      ) {
        return;
      }
      refreshPreview();
    });
    const unsubscribeConnect = previewWebSocket.onConnect(() => {
      if (hasConnected) refreshPreview();
      hasConnected = true;
    });
    previewWebSocket.connect(init.wsUrl);
    return () => {
      unsubscribeEvent();
      unsubscribeConnect();
      previewWebSocket.disconnect();
    };
  }, [previewWebSocket, state.init]);

  useEffect(() => () => {
    notifyLocalWebPreviewWindowWillClose();
    const init = initRef.current;
    if (!init || init.mode !== 'devServer' || !init.sessionId) return;
    void transport.stopSession({
      agentTaskId: init.agentTaskId,
      artifactId: init.artifactId,
      sessionId: init.sessionId,
    }).catch(() => undefined);
  }, [transport]);

  const targetUrl = state.init?.targetUrl ?? '';
  const previewContentUrl = state.init?.previewContentUrl ?? targetUrl;
  const feedbackFallbackUrl = previewContentUrl;
  const displayName = state.init?.displayName || 'Local web preview';
  const needsLocalServer = state.init?.mode === 'devServer' && !state.init.sessionId;
  const hasFeedbackReadyPreview = (
    state.init?.mode !== 'devServer'
    || session?.status === 'running'
    || session?.status === 'stopped'
  ) && !isHistorical;
  const canSendFeedback = hasFeedbackReadyPreview && feedbackText.trim().length > 0 && !isSubmitting;
  // Always append the revision as a cache-busting query param -- for
  // devServer mode this is the same http://127.0.0.1 URL on every refresh,
  // and relying solely on the iframe's `key` remount to force a fresh fetch
  // is not reliable against WKWebView's HTTP cache once the dev server's
  // served file has been mutated on disk without changing its URL.
  const renderedPreviewUrl = previewUrlWithRevision(previewContentUrl, previewRevision);
  const statusText = lastUpdateMessage || statusLabel(state.status);
  const liveHtmlPreviewProps: LiveHtmlPreviewSurfaceProps = {
    status: state.status,
    statusText,
    errorMessage: state.errorMessage,
    session,
    renderedPreviewUrl,
    targetUrl,
    isHistorical,
    historicalDiff,
    historicalViewMode,
    setHistoricalViewMode,
    hasVersionHistory,
    canDiffHistorical,
    managed,
    needsLocalServer,
    serverForm: {
      command: serverCommand,
      args: serverArgs,
      cwd: serverCwd,
      port: serverPort,
      setCommand: setServerCommand,
      setArgs: setServerArgs,
      setCwd: setServerCwd,
      setPort: setServerPort,
    },
    isStartingServer,
    startServer: () => void handleStartServer(),
    stopServer: () => void handleStopServer(),
    refresh: () => {
      setLastUpdateMessage('Preview updated');
      setPreviewRevision(current => current + 1);
    },
    displayName,
    previewFrameRef,
    onFrameLoad: () => setState(current => ({ ...current, status: 'ready' })),
    onFrameError: () => setState(current => ({ ...current, status: 'error', errorMessage: 'The preview could not be loaded.' })),
  };

  const handleSendFeedback = async (providedText?: string) => {
    const init = state.init ?? initRef.current;
    const submittedText = (providedText ?? feedbackText).trim();
    if (
      !init
      || !hasFeedbackReadyPreview
      || !submittedText
      || submittedText.length > MAX_FEEDBACK_CHARS
      || isSubmitting
    ) {
      return;
    }
    setIsSubmitting(true);
    setFeedbackError(undefined);
    try {
      const [screenshot, requestedConsoleEvidence, previewLocation] = await Promise.all([
        captureScreenshot(),
        consoleEvidenceRef.current || state.consoleEvidence
          ? Promise.resolve(consoleEvidenceRef.current || state.consoleEvidence || '')
          : requestConsoleEvidence(),
        Promise.resolve(
          init.mode === 'static'
            ? { url: feedbackFallbackUrl, status: 'fallback' as const }
            : readCurrentPreviewUrl(previewFrameRef.current, feedbackFallbackUrl),
        ),
      ]);
      const evidenceBlock = requestedConsoleEvidence.trim()
        ? `\n\nConsole evidence:\n${requestedConsoleEvidence.trim()}`
        : '';
      await processAgentTask({
        agent_task: `Local web preview feedback on ${previewLocation.url}:\n\n${submittedText}${evidenceBlock}`,
        agent_task_id: crypto.randomUUID(),
        root_task_id: init.agentTaskId,
        previous_task_id: init.agentTaskId,
        reference_paths: screenshot.path ? [screenshot.path] : undefined,
        local_preview_feedback: {
          source_artifact_id: init.artifactId,
          mode: init.mode,
          preview_url: previewLocation.url,
          location_status: previewLocation.status,
          screenshot_path: screenshot.path,
          console_evidence: requestedConsoleEvidence,
          session_id: session?.sessionId,
          session_status: session?.status,
        },
      });
      setFeedbackText('');
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : 'Unable to send preview feedback.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStartServer = async (validationRequest?: LocalWebPreviewValidationServerPayload) => {
    const init = state.init ?? initRef.current;
    const command = validationRequest?.command ?? serverCommand.trim();
    const args = validationRequest?.args ?? (serverArgs.trim() ? serverArgs.trim().split(/\s+/) : []);
    const cwd = validationRequest?.cwd ?? serverCwd.trim();
    const port = validationRequest?.port ?? serverPort;
    const isExpectedValidationRequest = validationRequest
      && command === VALIDATION_SERVER_COMMAND
      && args.length === VALIDATION_SERVER_ARGS.length
      && args.every((value, index) => value === VALIDATION_SERVER_ARGS[index])
      && cwd === previewWorkingDirectory(init?.targetUrl ?? '')
      && port === VALIDATION_SERVER_PORT;
    if (
      !init
      || !command
      || !cwd
      || !Number.isInteger(port)
      || port < 1
      || port > 65_535
      || (validationRequest && !isExpectedValidationRequest)
    ) {
      setState(current => ({ ...current, status: 'error', errorMessage: 'Enter a command, working directory, and valid local port.' }));
      return;
    }
    setIsStartingServer(true);
    setState(current => ({ ...current, status: 'connecting', errorMessage: undefined }));
    try {
      const requestTransport = validationRequest
        ? createLocalWebPreviewTransport(() => typeof init.port === 'number' ? `http://localhost:${init.port}` : '')
        : transport;
      const session = await requestTransport.startSession({
        agentTaskId: init.agentTaskId,
        artifactId: init.artifactId,
        command,
        args,
        cwd,
        port,
      });
      if (session.status === 'running') {
        notifyLocalPreviewServerSessionStarted(session.sessionId);
      } else if (session.status === 'denied') {
        notifyLocalPreviewServerSessionDenied(session.sessionId, session.lastError ?? undefined);
      }
      const nextStatus: PreviewStatus = session.status === 'running'
        ? 'connecting'
        : session.status === 'denied'
          ? 'unsupported'
          : session.status === 'stopped'
            ? 'stopped'
            : 'error';
      setSession(session);
      if (session.status === 'running') {
        initRef.current = {
          ...init,
          targetUrl: session.url,
          sessionId: session.sessionId,
        };
      }
      setState(current => ({
        ...current,
        init: current.init && session.status === 'running' ? {
          ...current.init,
          targetUrl: session.url,
          sessionId: session.sessionId,
        } : current.init,
        status: nextStatus,
        errorMessage: session.status === 'running' ? undefined : session.lastError ?? 'The local preview server did not start.',
      }));
    } catch (error) {
      setState(current => ({
        ...current,
        status: 'error',
        errorMessage: error instanceof Error ? error.message : 'Unable to start the local preview server.',
      }));
    } finally {
      setIsStartingServer(false);
    }
  };

  validationFeedbackHandlerRef.current = (text) => {
    void handleSendFeedback(text);
  };
  validationServerHandlerRef.current = (payload) => {
    void handleStartServer(payload);
  };

  const handleStopServer = async () => {
    const init = state.init;
    if (!init || !init.sessionId) return;
    try {
      const stopped = await transport.stopSession({
        agentTaskId: init.agentTaskId,
        artifactId: init.artifactId,
        sessionId: init.sessionId,
      });
      setSession(stopped);
      setState(current => ({ ...current, status: 'stopped', errorMessage: undefined }));
    } catch (error) {
      setState(current => ({
        ...current,
        errorMessage: error instanceof Error ? error.message : 'Unable to stop the local preview server.',
      }));
    }
  };

  return (
    <div className="basil-webkit-window-frame">
      <div className="file-preview-window basil-webkit-window-surface">
        <header className="file-preview-window-header" ref={headerRef}>
          <div className="file-preview-window-controls" aria-label="Window controls">
            <button type="button" className="file-preview-window-control header-btn" aria-label="Close preview window" onClick={closeLocalWebPreviewWindow}>
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" /><line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" /><line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
            <button type="button" className="file-preview-window-control header-btn" aria-label="Minimize preview window" onClick={minimizeLocalWebPreviewWindow}>
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" /><line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" /></svg>
            </button>
          </div>
          <div className="file-preview-window-title-group">
            <div className="file-preview-window-eyebrow">Rendered preview</div>
            <h1 className="file-preview-window-title" title={displayName}>{displayName}</h1>
          </div>
          <div className="file-preview-window-actions">
            <span className={`local-web-preview-status local-web-preview-status--${state.status}`} role="status" aria-live="polite">{statusText}</span>
            <button type="button" className="local-web-preview-icon-button" aria-label="Refresh preview" title="Refresh preview" onClick={() => {
              setLastUpdateMessage('Preview updated');
              setPreviewRevision(current => current + 1);
            }}>
              <NativeSymbolIcon name="refresh" />
            </button>
            <button type="button" className="local-web-preview-icon-button" aria-label="Open in default browser" title="Open in default browser" onClick={() => openExternalUrl(targetUrl)}>
              <NativeSymbolIcon name="openExternal" />
            </button>
          </div>
        </header>
        <div className="file-preview-window-path" title={targetUrl}>{targetUrl}</div>
        {hasVersionHistory && (
          <div className="file-preview-window-version-row">
            <LiveHtmlPreviewHistoryToggle
              isHistorical={isHistorical}
              historicalViewMode={historicalViewMode}
              setHistoricalViewMode={setHistoricalViewMode}
              canDiffHistorical={canDiffHistorical}
            />
            <ManagedVersionControls
              state={managed.state}
              canRestore={managed.canRestore}
              onSelect={managed.selectVersion}
              onRestore={managed.restore}
            />
          </div>
        )}
        {hasVersionHistory && <ManagedVersionRestoreError state={managed.state} />}
        {initialHistoryLoadFailed && (
          <div className="file-preview-window-history-status" role="alert">
            <span>Version history is unavailable: {managed.state.errorMessage}</span>
            <button type="button" className="artifact-review-retry" onClick={managed.retry}>Retry</button>
          </div>
        )}
        {isHistorical && (
          <p className="local-web-preview-historical-note" role="status">
            Viewing an earlier version — static rendering, not live.
            {state.init?.mode === 'devServer' ? ' This does not reflect any server-side templating the dev server may apply.' : ''}
          </p>
        )}
        {session ? (
          <dl className="local-web-preview-lifecycle">
            <dt>Command</dt>
            <dd title={[session.command, ...session.args].join(' ')}>{[session.command, ...session.args].join(' ')}</dd>
            <dt>Working directory</dt>
            <dd title={session.cwd}>{session.cwd}</dd>
            <dt>Server</dt>
            <dd>{`${session.host}:${session.port}`}</dd>
            <dt>Status</dt>
            <dd>
              <span className={`local-web-preview-status local-web-preview-status--${state.status}`}>{statusText}</span>
              {(session.status === 'starting' || session.status === 'running') && (
                <button
                  type="button"
                  className="file-preview-window-action local-web-preview-stop-action"
                  onClick={() => void handleStopServer()}
                >
                  Stop preview
                </button>
              )}
            </dd>
          </dl>
        ) : null}
        <main className="file-preview-window-body local-web-preview-body">
          {selectedVersionIsLoading ? (
            <div className="file-preview-window-message" role="status">Loading selected version...</div>
          ) : selectedVersionLoadFailed ? (
            <div className="file-preview-window-message" role="alert">
              <p>Unable to load the selected version: {managed.state.errorMessage}</p>
              <button type="button" className="artifact-review-retry" onClick={managed.retry}>Retry</button>
            </div>
          ) : (
            <LiveHtmlPreviewSurface {...liveHtmlPreviewProps} />
          )}
        </main>
        <footer className="local-web-preview-feedback">
          <div className="local-web-preview-feedback-header">
            <label htmlFor="local-web-preview-feedback">Preview feedback</label>
            <span>{feedbackText.length}/{MAX_FEEDBACK_CHARS}</span>
          </div>
          <textarea id="local-web-preview-feedback" className="local-web-preview-feedback-input" value={feedbackText} maxLength={MAX_FEEDBACK_CHARS} placeholder="Describe what should change about this rendered page…" onChange={(event) => setFeedbackText(event.target.value)} />
          <div className="local-web-preview-feedback-actions">
            <button type="button" className="file-preview-window-action local-web-preview-send-action" disabled={!canSendFeedback} onClick={() => void handleSendFeedback()}>
              <NativeSymbolIcon name="send" />Send follow-up
            </button>
          </div>
          {feedbackError ? <p className="local-web-preview-feedback-error" role="alert">{feedbackError}</p> : null}
        </footer>
      </div>
    </div>
  );
}
