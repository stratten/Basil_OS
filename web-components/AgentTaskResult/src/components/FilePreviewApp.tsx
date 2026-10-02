import { useEffect, useMemo, useRef, useState } from 'react';
import MarkdownRenderer from './MarkdownRenderer';
import {
  filePreviewNameFromPath,
  presentFilePreview,
} from './artifacts/filePreviewPresentation';
import type { FilePreviewInitMessage } from '../types';
import {
  closeWidget,
  minimizeWidget,
  openContainingFolder,
  openFile,
  previewFile,
  registerFilePreviewInitHandler,
  registerFilePreviewUpdateHandler,
  reportFilePreviewChromeHeight,
  type FilePreviewPayload,
} from '../services/bridge';
import { setBaseUrl } from '../services/api';
import CrossfadeStack from '@shared/CrossfadeStack';
import { useManagedVersionHistory } from './artifacts/managedHistory/useManagedVersionHistory';
import { ManagedVersionControls, ManagedVersionRestoreError } from './artifacts/managedHistory/ManagedVersionControls';
import { diffLines, type DiffLine } from './artifacts/diffLines';
import { DiffView } from './artifacts/DiffView';

type PreviewStatus = 'waiting' | 'loading' | 'ready' | 'error';
type PreviewMode = 'render' | 'source' | 'diff';

interface PreviewState {
  status: PreviewStatus;
  path: string;
  payload?: FilePreviewPayload;
  error?: string;
}

interface PreviewContext {
  rootTaskId?: string;
  agentTaskId?: string;
}

function applyPreviewTheme(config: FilePreviewInitMessage) {
  const root = document.documentElement;
  if (config.theme) {
    root.style.setProperty('--background-primary', config.theme.backgroundPrimary);
    root.style.setProperty('--primary', config.theme.primary);
    root.style.setProperty('--secondary', config.theme.secondary);
    root.style.setProperty('--text-primary', config.theme.textPrimary);
    if (config.theme.recordingBase) {
      root.style.setProperty('--recording-base', config.theme.recordingBase);
    }
    if (config.theme.recordingAccent) {
      root.style.setProperty('--recording-accent', config.theme.recordingAccent);
    }
    if (config.theme.processingBase) {
      root.style.setProperty('--processing-base', config.theme.processingBase);
    }
    if (config.theme.processingAccent) {
      root.style.setProperty('--processing-accent', config.theme.processingAccent);
    }
    if (config.theme.warningBase) {
      root.style.setProperty('--warning-base', config.theme.warningBase);
    }
  }

  if (config.fonts) {
    root.style.setProperty('--font-family-light', config.fonts.fontFamily);
    root.style.setProperty('--font-family-medium', config.fonts.fontFamilyMedium);
    root.style.setProperty('--font-family-bold', config.fonts.fontFamilyBold);
  }
}

function defaultModeForKind(kind: FilePreviewPayload['kind'] | undefined): PreviewMode {
  return kind === 'markdown' ? 'render' : 'source';
}

export default function FilePreviewApp() {
  const [state, setState] = useState<PreviewState>({
    status: 'waiting',
    path: '',
  });
  const [context, setContext] = useState<PreviewContext>({});
  const [mode, setMode] = useState<PreviewMode>('source');
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const activePreviewRequestId = useRef<string>();

  useEffect(() => {
    registerFilePreviewInitHandler(config => {
      applyPreviewTheme(config);
      if (typeof config.port === 'number') {
        setBaseUrl(config.port);
      }
      setContext({ rootTaskId: config.rootTaskId, agentTaskId: config.agentTaskId });
      activePreviewRequestId.current = undefined;
      setState({ status: 'loading', path: config.path });

      previewFile(config.path)
        .then(payload => {
          activePreviewRequestId.current = payload.requestId;
          setState({
            status: payload.error ? 'error' : 'ready',
            path: payload.path || config.path,
            payload,
            error: payload.error,
          });
          setMode(defaultModeForKind(payload.kind));
        })
        .catch(error => {
          setState({
            status: 'error',
            path: config.path,
            error: error instanceof Error ? error.message : 'Unable to load file preview.',
          });
        });
    });
  }, []);

  useEffect(() => registerFilePreviewUpdateHandler(payload => {
    if (activePreviewRequestId.current !== payload.requestId) return;
    setState(current => (
      current.status === 'ready' && current.payload?.requestId === payload.requestId
        ? {
            status: payload.error ? 'error' : 'ready',
            path: payload.path || current.path,
            payload,
            error: payload.error,
          }
        : current
    ));
    setHistoryRefreshKey(current => current + 1);
  }), []);

  useEffect(() => {
    const measure = () => {
      const pathEl = document.querySelector('.file-preview-window-path');
      if (!pathEl) return;
      const height = Math.round(pathEl.getBoundingClientRect().bottom);
      if (height > 0) reportFilePreviewChromeHeight(height);
    };
    // Defer to next frame so fonts/theme applied by init have laid out.
    const id = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(id);
  }, [state.status]);

  const path = state.payload?.path || state.path;
  const name = state.payload?.name || filePreviewNameFromPath(path);
  const presentation = presentFilePreview(state.payload?.kind);
  const isVersionableKind = state.payload?.kind !== undefined
    && state.payload.kind !== 'pdf'
    && state.payload.kind !== 'unsupported';

  const managed = useManagedVersionHistory({
    canonicalPath: isVersionableKind ? path : undefined,
    enabled: isVersionableKind && state.status === 'ready',
    rootTaskId: context.rootTaskId,
    focusedAgentTaskId: context.agentTaskId,
    refreshKey: historyRefreshKey,
  });

  const hasVersionHistory = managed.state.versions.length > 0;
  const isHistoricalSelection = hasVersionHistory && managed.state.selectedIndex !== 0;
  const selectedVersionIsLoading = hasVersionHistory && managed.state.status === 'loading';
  const selectedVersionLoadFailed = hasVersionHistory && managed.state.status === 'error';
  const initialHistoryLoadFailed = !hasVersionHistory && managed.state.status === 'error';
  const displayedContent = hasVersionHistory ? managed.state.selectedContent : state.payload?.content;
  const canDiff = hasVersionHistory && managed.state.compareContent !== undefined;

  const diff = useMemo<DiffLine[] | undefined>(() => {
    if (mode !== 'diff' || !canDiff) return undefined;
    return diffLines(managed.state.compareContent ?? '', managed.state.selectedContent ?? '');
  }, [mode, canDiff, managed.state.compareContent, managed.state.selectedContent]);

  return (
    <div className="basil-webkit-window-frame">
      <div className="file-preview-window basil-webkit-window-surface">
      <header className="file-preview-window-header">
        <div className="file-preview-window-controls" aria-label="Window controls">
          <button
            type="button"
            className="file-preview-window-control header-btn"
            aria-label="Close preview window"
            title="Close"
            onClick={closeWidget}
          >
            <svg width="20" height="20" viewBox="0 0 22 22">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="file-preview-window-control header-btn"
            aria-label="Minimize preview window"
            title="Minimize"
            onClick={minimizeWidget}
          >
            <svg width="20" height="20" viewBox="0 0 22 22">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="file-preview-window-title-group">
          <div className="file-preview-window-eyebrow">{presentation.label}</div>
          <h1 className="file-preview-window-title" title={path}>{name}</h1>
        </div>
        <div className="file-preview-window-actions">
          <button
            type="button"
            className="file-preview-window-action"
            disabled={!path}
            onClick={() => openFile(path)}
          >
            Open File
          </button>
          <button
            type="button"
            className="file-preview-window-action"
            disabled={!path}
            onClick={() => openContainingFolder(path)}
          >
            Show in Folder
          </button>
        </div>
      </header>
      <div className="file-preview-window-path" title={path}>{path}</div>
      {hasVersionHistory && (
        <div className="file-preview-window-version-row">
          <div className="artifact-review-mode-toggle" role="tablist" aria-label="Preview mode">
            {(
              presentation.renderMode === 'markdown'
                ? (['render', 'source', 'diff'] as PreviewMode[])
                : (['source', 'diff'] as PreviewMode[])
            ).map(candidate => (
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
      <CrossfadeStack
        contentKey={`${state.status}:${state.payload?.requestId ?? ''}:${mode}:${hasVersionHistory ? managed.state.selectedIndex : ''}`}
        className="file-preview-window-body"
        as="main"
      >
        {state.status === 'waiting' || state.status === 'loading' ? (
          <div className="file-preview-window-message">Loading preview...</div>
        ) : state.status === 'error' ? (
          <div className="file-preview-window-message">{state.error || 'Unable to load file preview.'}</div>
        ) : selectedVersionIsLoading ? (
          <div className="file-preview-window-message" role="status">Loading selected version...</div>
        ) : selectedVersionLoadFailed ? (
          <div className="file-preview-window-message" role="alert">
            <p>Unable to load the selected version: {managed.state.errorMessage}</p>
            <button type="button" className="artifact-review-retry" onClick={managed.retry}>Retry</button>
          </div>
        ) : mode === 'diff' && diff ? (
          <DiffView diff={diff} label={`Diff for ${name}`} />
        ) : mode === 'render' && presentation.renderMode === 'markdown' && !isHistoricalSelection && displayedContent ? (
          <div className="file-preview-window-markdown">
            <MarkdownRenderer content={displayedContent} />
          </div>
        ) : mode === 'render' && presentation.renderMode === 'markdown' && isHistoricalSelection && displayedContent !== undefined ? (
          <MarkdownRenderer content={displayedContent} />
        ) : presentation.renderMode === 'native_pdf' ? (
          <div className="file-preview-window-pdf-placeholder" aria-hidden="true" />
        ) : displayedContent !== undefined && (presentation.renderMode === 'source' || presentation.renderMode === 'markdown' || presentation.renderMode === 'live_html') ? (
          <pre className="file-preview-window-source"><code>{displayedContent}</code></pre>
        ) : (
          <div className="file-preview-window-message">This file type is not supported by the in-app preview.</div>
        )}
      </CrossfadeStack>
      </div>
    </div>
  );
}
