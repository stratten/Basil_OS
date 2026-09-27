import type { RefObject } from 'react';
import NativeSymbolIcon from '../../../../../shared/NativeSymbolIcon';
import { sandboxedHtmlDocument } from '../managedHistory/managedVersionPresentation';
import { DiffView } from '../DiffView';
import type { UseLiveHtmlPreviewResult } from './useLiveHtmlPreview';

export interface LiveHtmlPreviewSurfaceProps extends UseLiveHtmlPreviewResult {
  displayName: string;
  previewFrameRef?: RefObject<HTMLIFrameElement>;
  onFrameLoad?: () => void;
  onFrameError?: () => void;
  className?: string;
}

/**
 * Renders just the preview body -- historical diff/render, "start a local
 * server" setup form, error/unsupported states, and the live scripted
 * iframe. Window chrome (title bar, close/minimize controls, feedback
 * footer, screenshot capture) is host-specific and stays outside this
 * component; both the detached LocalWebPreviewApp and the inline tray
 * surfaces wrap this with their own chrome.
 */
export function LiveHtmlPreviewSurface({
  displayName,
  previewFrameRef,
  onFrameLoad,
  onFrameError,
  className,
  status,
  errorMessage,
  renderedPreviewUrl,
  isHistorical,
  historicalDiff,
  historicalViewMode,
  hasVersionHistory,
  managed,
  needsLocalServer,
  serverForm,
  isStartingServer,
  startServer,
}: LiveHtmlPreviewSurfaceProps) {
  const frameClassName = ['local-web-preview-frame', className].filter(Boolean).join(' ');

  if (managed.state.status === 'loading' && hasVersionHistory && managed.state.selectedIndex !== 0) {
    return <div className="file-preview-window-message" role="status">Loading selected version.</div>;
  }
  if (managed.state.status === 'error' && hasVersionHistory) {
    return (
      <div className="file-preview-window-message" role="alert">
        <p>Unable to load the selected version: {managed.state.errorMessage}</p>
        <button type="button" className="artifact-review-retry" onClick={managed.retry}>Retry</button>
      </div>
    );
  }
  if (isHistorical && historicalViewMode === 'diff' && historicalDiff) {
    return <DiffView diff={historicalDiff} label={`Diff for ${displayName}`} />;
  }
  if (isHistorical) {
    return (
      <iframe
        key={`historical:${managed.state.selectedIndex}`}
        className={frameClassName}
        title={`${displayName} preview (earlier version)`}
        sandbox=""
        srcDoc={sandboxedHtmlDocument(managed.state.selectedContent ?? '')}
      />
    );
  }
  if (needsLocalServer) {
    return (
      <section className="file-preview-window-message local-web-preview-server-setup" aria-label="Local server setup">
        <p>Start a local server to render this artifact. Basil will request approval before running the command.</p>
        <div className="local-web-preview-field-grid">
          <label>Command<input value={serverForm.command} onChange={event => serverForm.setCommand(event.target.value)} placeholder="npm" /></label>
          <label>Arguments<input value={serverForm.args} onChange={event => serverForm.setArgs(event.target.value)} placeholder="run dev -- --host 127.0.0.1 --port 4173" /></label>
          <label>Working directory<input value={serverForm.cwd} onChange={event => serverForm.setCwd(event.target.value)} placeholder="/path/to/project" /></label>
          <label>Port<input type="number" min="1" max="65535" value={serverForm.port} onChange={event => serverForm.setPort(Number(event.target.value))} /></label>
        </div>
        <button type="button" className="file-preview-window-action local-web-preview-start-action" disabled={isStartingServer} onClick={startServer}>
          <NativeSymbolIcon name="play" />{isStartingServer ? 'Requesting approval…' : 'Preview with a local server'}
        </button>
        {errorMessage ? <p className="local-web-preview-feedback-error" role="alert">{errorMessage}</p> : null}
      </section>
    );
  }
  if (status === 'unsupported' || status === 'error' || status === 'stopped') {
    return <p className="file-preview-window-message" role="alert">{errorMessage || 'This preview is unavailable.'}</p>;
  }
  return (
    <iframe
      ref={previewFrameRef}
      className={frameClassName}
      key={renderedPreviewUrl}
      title={`${displayName} preview`}
      sandbox="allow-scripts allow-same-origin"
      src={renderedPreviewUrl}
      onLoad={onFrameLoad}
      onError={onFrameError}
    />
  );
}

export function LiveHtmlPreviewHistoryToggle({
  isHistorical,
  historicalViewMode,
  setHistoricalViewMode,
  canDiffHistorical,
}: Pick<UseLiveHtmlPreviewResult, 'isHistorical' | 'historicalViewMode' | 'setHistoricalViewMode' | 'canDiffHistorical'>) {
  if (!isHistorical) return null;
  return (
    <div className="artifact-review-mode-toggle" role="tablist" aria-label="Historical version view">
      {(['render', 'diff'] as const).map(candidate => (
        <button
          key={candidate}
          type="button"
          role="tab"
          aria-selected={historicalViewMode === candidate}
          disabled={candidate === 'diff' && !canDiffHistorical}
          className={`artifact-review-mode${historicalViewMode === candidate ? ' is-active' : ''}`}
          onClick={() => setHistoricalViewMode(candidate)}
          title={candidate === 'diff' && !canDiffHistorical ? 'A prior version is required to show a diff.' : undefined}
        >
          {candidate === 'render' ? 'Render' : 'Diff'}
        </button>
      ))}
    </div>
  );
}
