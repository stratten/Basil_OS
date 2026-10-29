import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createLocalWebPreviewTransport,
  type LocalWebPreviewSessionDTO,
} from '../transport/localWebPreviewTransport';
import {
  useManagedVersionHistory,
  type UseManagedVersionHistoryResult,
} from '../managedHistory/useManagedVersionHistory';
import { diffLines, type DiffLine } from '../diffLines';

const DEFAULT_LOCAL_SERVER_PORT = 4173;
const SESSION_POLL_INTERVAL_MS = 1_000;

export type LivePreviewStatus = 'connecting' | 'ready' | 'stopped' | 'error' | 'unsupported';
export type LivePreviewHistoricalViewMode = 'render' | 'diff';

export interface UseLiveHtmlPreviewParams {
  mode: 'static' | 'devServer';
  targetUrl: string;
  previewContentUrl?: string;
  agentTaskId: string;
  artifactId: string;
  rootTaskId?: string;
  canonicalPath?: string;
  sessionId?: string;
  displayName?: string;
  /**
   * Notifies the hook that this artifact changed on disk (e.g. a websocket
   * `agent_task_artifact` event); the hook does not own any connection
   * itself, so callers own filtering by agentTaskId/artifactId and wiring
   * up whichever transport (shared app websocket, or a dedicated per-window
   * one) is appropriate for their host.
   */
  subscribeToArtifactEvents: (onEvent: () => void) => () => void;
  getApiBaseUrl: () => string;
  /**
   * When supplied, the hook uses this instead of creating its own
   * `useManagedVersionHistory` call. ArtifactReviewWorkspace already fetches
   * version history for its own version dropdown; without this, the hook's
   * internal call would issue a redundant fetch for the same canonicalPath.
   */
  externalManagedHistory?: UseManagedVersionHistoryResult;
  /**
   * Detached preview windows stop their dev-server session when the window
   * closes (this hook unmounting). Inline tray usage unmounts far more
   * often (switching tabs/artifacts) and should not tear down a running
   * server just because the surface is momentarily off-screen, so this
   * defaults to false and only the detached window opts in.
   */
  stopServerOnUnmount?: boolean;
}

export interface LiveHtmlPreviewServerForm {
  command: string;
  args: string;
  cwd: string;
  port: number;
  setCommand: (value: string) => void;
  setArgs: (value: string) => void;
  setCwd: (value: string) => void;
  setPort: (value: number) => void;
}

export interface UseLiveHtmlPreviewResult {
  status: LivePreviewStatus;
  statusText: string;
  errorMessage?: string;
  session?: LocalWebPreviewSessionDTO;
  renderedPreviewUrl: string;
  targetUrl: string;
  isHistorical: boolean;
  historicalDiff?: DiffLine[];
  historicalViewMode: LivePreviewHistoricalViewMode;
  setHistoricalViewMode: (mode: LivePreviewHistoricalViewMode) => void;
  hasVersionHistory: boolean;
  canDiffHistorical: boolean;
  managed: UseManagedVersionHistoryResult;
  needsLocalServer: boolean;
  serverForm: LiveHtmlPreviewServerForm;
  isStartingServer: boolean;
  startServer: () => void;
  stopServer: () => void;
  refresh: () => void;
}

interface EffectiveTarget {
  targetUrl: string;
  sessionId?: string;
}

function statusLabel(status: LivePreviewStatus): string {
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

export function useLiveHtmlPreview(params: UseLiveHtmlPreviewParams): UseLiveHtmlPreviewResult {
  const {
    mode,
    targetUrl,
    previewContentUrl,
    agentTaskId,
    artifactId,
    rootTaskId,
    canonicalPath,
    sessionId,
    subscribeToArtifactEvents,
    getApiBaseUrl,
    externalManagedHistory,
    stopServerOnUnmount = false,
  } = params;

  const [effective, setEffective] = useState<EffectiveTarget>({ targetUrl, sessionId });
  const [status, setStatus] = useState<LivePreviewStatus>(
    mode === 'devServer' && !sessionId ? 'unsupported' : 'connecting',
  );
  const [errorMessage, setErrorMessage] = useState<string>();
  const [session, setSession] = useState<LocalWebPreviewSessionDTO>();
  const [serverCommand, setServerCommand] = useState('');
  const [serverArgs, setServerArgs] = useState('');
  const [serverCwd, setServerCwd] = useState('');
  const [serverPort, setServerPort] = useState(DEFAULT_LOCAL_SERVER_PORT);
  const [isStartingServer, setIsStartingServer] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [lastUpdateMessage, setLastUpdateMessage] = useState('');
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [historicalViewMode, setHistoricalViewMode] = useState<LivePreviewHistoricalViewMode>('render');
  const previousHeadChangeId = useRef<string | undefined>(undefined);

  const transport = useMemo(() => createLocalWebPreviewTransport(getApiBaseUrl), [getApiBaseUrl]);

  const ownManaged = useManagedVersionHistory({
    canonicalPath: externalManagedHistory ? undefined : canonicalPath,
    enabled: !externalManagedHistory && Boolean(canonicalPath),
    rootTaskId,
    focusedAgentTaskId: agentTaskId,
    refreshKey: historyRefreshKey,
  });
  const managed = externalManagedHistory ?? ownManaged;

  const hasVersionHistory = managed.state.versions.length > 0;
  const isHistorical = hasVersionHistory && managed.state.selectedIndex !== 0;
  const canDiffHistorical = managed.state.compareContent !== undefined;

  const historicalDiff = useMemo<DiffLine[] | undefined>(() => {
    if (!isHistorical || historicalViewMode !== 'diff' || !canDiffHistorical) return undefined;
    return diffLines(managed.state.compareContent ?? '', managed.state.selectedContent ?? '');
  }, [isHistorical, historicalViewMode, canDiffHistorical, managed.state.compareContent, managed.state.selectedContent]);

  useEffect(() => {
    if (!isHistorical) setHistoricalViewMode('render');
  }, [isHistorical]);

  // After a restore, the history hook resets to index 0 pointing at the
  // newly-recorded head version. Detect that head-id change and reuse the
  // cache-busting revision counter to force the live iframe to reload the
  // now-restored disk content.
  useEffect(() => {
    const headId = managed.state.versions[0]?.id;
    if (headId && previousHeadChangeId.current && headId !== previousHeadChangeId.current) {
      setPreviewRevision(current => current + 1);
      setLastUpdateMessage('Preview updated');
    }
    previousHeadChangeId.current = headId;
  }, [managed.state.versions]);

  // Reset all preview state when the identity of what's being previewed
  // changes (new artifact, new mode, or a freshly-started server session
  // replacing the "needs local server" placeholder).
  useEffect(() => {
    setEffective({ targetUrl, sessionId });
    setServerCwd(previewWorkingDirectory(targetUrl));
    setPreviewRevision(0);
    setLastUpdateMessage('');
    setSession(undefined);
    setErrorMessage(undefined);
    setStatus(mode === 'devServer' && !sessionId ? 'unsupported' : 'connecting');
  }, [mode, targetUrl, artifactId, sessionId]);

  useEffect(() => {
    if (mode !== 'devServer' || !effective.sessionId) return;
    let isCurrent = true;
    const refreshSession = async () => {
      try {
        const polledSession = await transport.getSession({
          agentTaskId,
          artifactId,
          sessionId: effective.sessionId!,
        });
        if (!isCurrent) return;
        setSession(polledSession);
        if (polledSession.status === 'running') return;
        setStatus(
          polledSession.status === 'stopped' ? 'stopped' : polledSession.status === 'denied' ? 'unsupported' : 'error',
        );
        setErrorMessage(
          polledSession.lastError ?? (polledSession.status === 'stopped' ? 'The local preview server stopped.' : 'The local preview server is unavailable.'),
        );
      } catch (error) {
        if (!isCurrent) return;
        setSession(undefined);
        setStatus('error');
        setErrorMessage(error instanceof Error ? error.message : 'Unable to check local preview server status.');
      }
    };
    void refreshSession();
    const intervalId = window.setInterval(() => void refreshSession(), SESSION_POLL_INTERVAL_MS);
    return () => {
      isCurrent = false;
      window.clearInterval(intervalId);
    };
  }, [mode, effective.sessionId, agentTaskId, artifactId, transport]);

  useEffect(() => {
    const refreshPreview = () => {
      setLastUpdateMessage('Preview updated');
      setPreviewRevision(current => current + 1);
      setHistoryRefreshKey(current => current + 1);
    };
    return subscribeToArtifactEvents(refreshPreview);
  }, [subscribeToArtifactEvents]);

  useEffect(() => {
    if (!stopServerOnUnmount) return;
    return () => {
      if (mode !== 'devServer' || !effective.sessionId) return;
      void transport.stopSession({ agentTaskId, artifactId, sessionId: effective.sessionId }).catch(() => undefined);
    };
    // Intentionally only depends on mount/unmount identity, mirroring the
    // detached window's "stop on window close" cleanup effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const needsLocalServer = mode === 'devServer' && !effective.sessionId;
  const previewContentTarget = previewContentUrl ?? effective.targetUrl;
  const renderedPreviewUrl = previewUrlWithRevision(previewContentTarget, previewRevision);
  const statusText = lastUpdateMessage || statusLabel(status);

  const startServer = () => {
    const command = serverCommand.trim();
    const args = serverArgs.trim() ? serverArgs.trim().split(/\s+/) : [];
    const cwd = serverCwd.trim();
    const port = serverPort;
    if (!command || !cwd || !Number.isInteger(port) || port < 1 || port > 65_535) {
      setStatus('error');
      setErrorMessage('Enter a command, working directory, and valid local port.');
      return;
    }
    setIsStartingServer(true);
    setStatus('connecting');
    setErrorMessage(undefined);
    void (async () => {
      try {
        const startedSession = await transport.startSession({ agentTaskId, artifactId, command, args, cwd, port });
        setSession(startedSession);
        if (startedSession.status === 'running') {
          setEffective({ targetUrl: startedSession.url, sessionId: startedSession.sessionId });
          setStatus('connecting');
          setErrorMessage(undefined);
        } else {
          setStatus(
            startedSession.status === 'denied' ? 'unsupported' : startedSession.status === 'stopped' ? 'stopped' : 'error',
          );
          setErrorMessage(startedSession.lastError ?? 'The local preview server did not start.');
        }
      } catch (error) {
        setStatus('error');
        setErrorMessage(error instanceof Error ? error.message : 'Unable to start the local preview server.');
      } finally {
        setIsStartingServer(false);
      }
    })();
  };

  const stopServer = () => {
    if (!effective.sessionId) return;
    void (async () => {
      try {
        const stopped = await transport.stopSession({ agentTaskId, artifactId, sessionId: effective.sessionId! });
        setSession(stopped);
        setStatus('stopped');
        setErrorMessage(undefined);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : 'Unable to stop the local preview server.');
      }
    })();
  };

  const refresh = () => {
    setLastUpdateMessage('Preview updated');
    setPreviewRevision(current => current + 1);
  };

  return {
    status,
    statusText,
    errorMessage,
    session,
    renderedPreviewUrl,
    targetUrl: effective.targetUrl,
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
    startServer,
    stopServer,
    refresh,
  };
}
