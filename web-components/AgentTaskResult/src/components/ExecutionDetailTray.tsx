import type { AgentTaskArtifactPresentation } from '../artifacts/artifactContract';
import type { StepDetailEntry, TimelineEntry } from '../types';
import type { TransitionEvent } from 'react';
import MarkdownRenderer from './MarkdownRenderer';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
import { canRequestInlinePreview, InlineArtifactPreview } from './artifacts/InlineArtifactPreview';
import { ArtifactPreviewActionBar } from './artifacts/ArtifactPreviewActionBar';
import { ArtifactReviewDocumentTabs, ArtifactReviewWorkspace } from './artifacts/ArtifactReviewWorkspace';
import type { DerivedAgentTaskArtifact, DerivedAgentTaskArtifacts } from './artifacts/artifactDerivation';
import type { AgentRunOverviewPresentation, AgentRunPresentation, AgentRunStage } from './run/agentRunPresentation';
import { deriveAgentRunOverviewPresentation, deriveAgentRunPresentation } from './run/agentRunPresentation';
import { AgentRunHistoryTray } from './run/AgentRunHistoryTray';
import type { AgentTaskRunFocusSummary } from './run/agentTaskRunFocus';
import NativeSymbolIcon, { type NativeSymbolName } from '../../../shared/NativeSymbolIcon';
import { agentTaskArtifactPreviewTransport } from '../services/bridge';
import { wsManager, type AgentTaskEventSubscriber } from '../services/websocket';
import {
  clampDetailTrayWidth,
  DETAIL_TRAY_KEYBOARD_STEP,
  DETAIL_TRAY_MIN_WIDTH,
} from '../app/detailTraySizing';
import type { PresencePhase } from '../app/usePresenceTransition';

const RESIZE_ACTIVATION_DISTANCE_PX = 4;

const subscribeToAgentTaskEvents: AgentTaskEventSubscriber = handler => wsManager.subscribe(handler);

function logTrayDiagnostic(event: string, payload: Record<string, unknown>): void {
  console.log(`[AgentTaskResult][ExecutionDetailTray][${event}] ${JSON.stringify(payload)}`);
}

interface Props {
  detail?: StepDetailEntry;
  isOpen: boolean;
  presencePhase: PresencePhase;
  onPresenceTransitionEnd: (event: TransitionEvent<HTMLElement>) => void;
  trayWidth: number;
  onTrayWidthChange: (width: number) => void;
  /**
   * Reports whether a live drag on the resize handle is in progress, so the
   * host can suppress native window-resize requests until the drag ends.
   * See `useResultWidgetSizing`'s `setTrayResizing`/`isTrayResizingRef` for
   * why: an animated `NSWindow.setFrame` mid-drag steals the OS-level
   * mouse-tracking loop that WebKit's pointer capture depends on, which is
   * what actually produces the "tray collapses on the very first resize
   * drag" symptom.
   */
  onResizingChange?: (isResizing: boolean) => void;
  followLatest: boolean;
  hasNewerDetail: boolean;
  onClose: () => void;
  onJumpToLatest: () => void;
  artifacts: DerivedAgentTaskArtifacts;
  timeline: TimelineEntry[];
  runPresentation?: AgentRunPresentation;
  overviewPresentation?: AgentRunOverviewPresentation;
  isProcessing: boolean;
  terminalStatus: string;
  agentTaskId: string;
  rootTaskId: string;
  focusedRunId: string;
  previewArtifact?: DerivedAgentTaskArtifact;
  isPreviewArtifactFileAvailable: boolean;
  onPreviewArtifact: (artifactId: string) => void;
  onClosePreview: () => void;
  onCloseRunPanel: () => void;
  runs: AgentTaskRunFocusSummary[];
  onFocusRun: (runId: string) => void;
}

function formatDetailKind(kind?: string): string {
  if (!kind) return 'Detail';
  return kind
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function ArtifactDetail({ artifact, onPreviewArtifact }: {
  artifact: AgentTaskArtifactPresentation;
  onPreviewArtifact: (artifactId: string) => void;
}) {
  const canPreview = canRequestInlinePreview(artifact);
  return (
    <section className="detail-tray-artifact" aria-label="Artifact">
      <p className="detail-tray-artifact-name" title={artifact.displayName}>{artifact.displayName}</p>
      {artifact.lifecycle === 'unavailable' && <p className="detail-tray-artifact-unavailable">Artifact unavailable</p>}
      {canPreview && (
        <button
          type="button"
          className="detail-tray-link detail-tray-artifact-link"
          onClick={() => onPreviewArtifact(artifact.artifactId)}
        >
          Preview {artifact.displayName}
        </button>
      )}
    </section>
  );
}

function RunStageGlyph({ stage }: { stage: Pick<AgentRunStage, 'kind' | 'state'> }) {
  if (stage.state === 'failed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>;
  }
  if (stage.kind === 'artifact') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg>;
  }
  if (stage.state === 'completed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.2 4.2L19 7.5" /></svg>;
  }
  if (stage.kind === 'tool') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /><path d="M12 8v4l2.5 2.5" /></svg>;
}

function PreviewActionIcon({ action }: { action: 'open-file' | 'show-in-folder' | 'open-preview-window' | 'open-local-web-preview' | 'open-local-web-preview-server' | 'close-preview' | 'collapse-panel' }) {
  if (action === 'open-file') {
    return <RunStageGlyph stage={{ kind: 'artifact', state: 'completed' }} />;
  }
  const symbolName: NativeSymbolName = action === 'show-in-folder'
    ? 'folder'
    : action === 'open-preview-window'
      ? 'openPreview'
      : action === 'open-local-web-preview'
        ? 'openLocalWebPreview'
        : action === 'open-local-web-preview-server'
          ? 'play'
          : action === 'collapse-panel'
            ? 'collapse'
            : 'close';
  // close-preview/collapse-panel render at 14px everywhere in this tray (rather
  // than NativeSymbolIcon's 16px default for those symbols) so they match the
  // size of the other action icons around them here -- there's no spot in this
  // component where the larger default size is actually wanted.
  const size = symbolName === 'close' || symbolName === 'collapse' ? 14 : undefined;
  return <NativeSymbolIcon name={symbolName} className="tray-artifact-preview-symbol" size={size} />;
}

function RunCard({
  artifacts,
  presentation,
  isProcessing,
  onPreviewArtifact,
}: {
  artifacts: DerivedAgentTaskArtifacts;
  presentation: AgentRunOverviewPresentation;
  isProcessing: boolean;
  onPreviewArtifact: (artifactId: string) => void;
}) {
  const terminalStateLabel = isProcessing
    ? 'Working now'
    : presentation.terminalState === 'completed'
      ? 'Ready for review'
      : 'Needs attention';

  return (
    <section className="run-card" aria-label="Run overview">
      {presentation.stages.length > 0 ? (
        <ol className="run-card-stages">
          {presentation.stages.map(stage => (
            <li className={`run-card-stage run-card-stage--${stage.kind} is-${stage.state}`} key={stage.id}>
              <span className="run-card-stage-glyph" aria-hidden="true"><RunStageGlyph stage={stage} /></span>
              <span className="run-card-stage-label">{stage.label}</span>
              {stage.kind === 'outcome' ? (
                <span className="run-card-stage-evidence">{terminalStateLabel}</span>
              ) : stage.artifactCount > 0 ? (
                <span className="run-card-stage-evidence">{stage.artifactCount} document{stage.artifactCount === 1 ? '' : 's'}</span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="run-card-empty">{isProcessing ? 'Waiting for the first meaningful stage.' : 'No high-level stages were recorded.'}</p>
      )}
      {artifacts.produced.length > 0 && (
        <div className="run-card-artifacts" aria-label="Created documents">
          {artifacts.produced.map(artifact => (
            <button className="run-card-artifact" type="button" key={artifact.artifactId} onClick={() => onPreviewArtifact(artifact.artifactId)} aria-label={`Preview ${artifact.displayName}`}>
              <RunStageGlyph stage={{ kind: 'artifact', state: 'completed' }} />
              <span>{artifact.displayName}</span>
              {artifact.review && artifact.review.revisionCount > 1 && (
                <span className="run-card-artifact-badge">v{artifact.review.revisionCount}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function renderMetadata(metadata?: Record<string, unknown>) {
  if (!metadata || Object.keys(metadata).length === 0) return null;
  const visibleEntries = Object.entries(metadata)
    .filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (visibleEntries.length === 0) return null;

  return (
    <div className="detail-tray-metadata">
      {visibleEntries.map(([key, value]) => (
        <div key={key} className="detail-tray-metadata-row">
          <span className="detail-tray-metadata-key">{key.replace(/_/g, ' ')}</span>
          <span className="detail-tray-metadata-value">
            {typeof value === 'string' ? value : JSON.stringify(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function parsePossibleJson(text: string): unknown | null {
  const trimmed = text.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function stringifyValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function normalizeDisplayNewlines(text: string): string {
  return text
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n');
}

function firstNonEmpty(...values: unknown[]): string {
  for (const value of values) {
    const text = normalizeDisplayNewlines(stringifyValue(value)).trim();
    if (text) return text;
  }
  return '';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function formatMaybeLink(value: unknown): string {
  const text = stringifyValue(value).trim();
  if (!text) return '';
  if (text.startsWith('http://') || text.startsWith('https://')) {
    return `[${text}](${text})`;
  }
  return text;
}

function formatExternalCatalogPayload(data: Record<string, unknown>, detail: StepDetailEntry): string | null {
  const toolName = stringifyValue(detail.metadata?.tool_name).toLowerCase();
  const action = firstNonEmpty(data.action);
  const looksLikeCatalog =
    toolName.includes('external_catalog') ||
    action === 'list_servers' ||
    action === 'describe_server' ||
    action === 'call_tool' ||
    typeof data.ok === 'boolean';

  if (!looksLikeCatalog) return null;

  const sections: string[] = [];
  const ok = data.ok;
  if (typeof ok === 'boolean') {
    sections.push(ok ? 'External service call completed successfully.' : 'External service call reported a problem.');
  } else if (action) {
    sections.push(`Preparing external service action: **${action}**.`);
  }

  const error = asRecord(data.error);
  if (error) {
    const message = firstNonEmpty(error.message, error.kind);
    if (message) sections.push(`**Problem:** ${message}`);
    const nextStep = firstNonEmpty(error.user_action_required);
    if (nextStep) sections.push(`**What to do next:** ${nextStep}`);
  }

  const result = asRecord(data.result);
  const servers = asArray(result?.servers);
  if (servers.length > 0) {
    const serverLines = servers.slice(0, 6).map(serverValue => {
      const server = asRecord(serverValue) || {};
      const name = firstNonEmpty(server.friendly_name, server.name, 'External service');
      const count = firstNonEmpty(server.tool_count);
      const url = formatMaybeLink(server.server_url);
      return `- **${name}**${count ? `: ${count} tools` : ''}${url ? ` (${url})` : ''}`;
    });
    if (servers.length > serverLines.length) {
      serverLines.push(`- … ${servers.length - serverLines.length} more services`);
    }
    sections.push(`**Available services:**\n${serverLines.join('\n')}`);
  }

  const tools = asArray(result?.tools);
  if (tools.length > 0) {
    const connectionName = firstNonEmpty(result?.friendly_name, asRecord(result?.server)?.name, 'this service');
    const toolLines = tools.slice(0, 8).map(toolValue => {
      const tool = asRecord(toolValue) || {};
      const name = firstNonEmpty(tool.name, 'Unnamed tool');
      const readOnly = tool.is_read_only_hint === true ? 'read-only' : 'may change data';
      return `- **${name}** (${readOnly})`;
    });
    if (tools.length > toolLines.length) {
      toolLines.push(`- … ${tools.length - toolLines.length} more tools`);
    }
    sections.push(`**Tools on ${connectionName}:**\n${toolLines.join('\n')}`);
  }

  const calledTool = firstNonEmpty(data.tool_name, result?.tool_name);
  if (calledTool) sections.push(`**Tool used:** ${calledTool}`);

  const output = firstNonEmpty(
    result?.text,
    result?.content,
    result?.structuredContent,
    data.summary,
    data.message
  );
  if (output) sections.push(`**Result preview:**\n${output}`);

  return sections.length > 0 ? sections.join('\n\n') : null;
}

function formatToolResult(data: Record<string, unknown>, detail: StepDetailEntry): string {
  const externalCatalogSummary = formatExternalCatalogPayload(data, detail);
  if (externalCatalogSummary) return externalCatalogSummary;

  const sections: string[] = [];
  const success = data.success;
  if (typeof success === 'boolean') {
    sections.push(success ? 'The tool completed successfully.' : 'The tool reported a problem.');
  }

  const query = firstNonEmpty(data.query);
  if (query) sections.push(`**Search query:** ${query}`);

  const focus = firstNonEmpty(data.focus);
  if (focus) sections.push(`**Focus:** ${focus}`);

  const output = firstNonEmpty(
    data.summary,
    data.summary_text,
    data.result,
    data.output,
    data.search_results,
    data.message,
    data.error,
    detail.body
  );
  if (output) sections.push(output);

  return sections.join('\n\n') || normalizeDisplayNewlines(detail.body || detail.content);
}

function formatDetailBody(detail: StepDetailEntry): { userMarkdown: string; raw?: string } {
  const rawBody = detail.body || detail.content || '';
  const parsed = parsePossibleJson(rawBody);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return {
      userMarkdown: formatToolResult(parsed as Record<string, unknown>, detail),
      raw: JSON.stringify(parsed, null, 2),
    };
  }

  return { userMarkdown: normalizeDisplayNewlines(rawBody) };
}

export default function ExecutionDetailTray({
  detail,
  isOpen,
  presencePhase,
  onPresenceTransitionEnd,
  trayWidth,
  onTrayWidthChange,
  onResizingChange,
  followLatest,
  hasNewerDetail,
  onClose,
  onJumpToLatest,
  artifacts,
  timeline,
  runPresentation,
  overviewPresentation,
  isProcessing,
  terminalStatus,
  agentTaskId,
  rootTaskId,
  focusedRunId,
  previewArtifact,
  isPreviewArtifactFileAvailable,
  onPreviewArtifact,
  onClosePreview,
  onCloseRunPanel,
  runs,
  onFocusRun,
}: Props) {
  const [showRaw, setShowRaw] = useState(false);
  const formatted = useMemo(
    () => detail && !detail.artifact ? formatDetailBody(detail) : { userMarkdown: '' },
    [detail],
  );
  const previewProvenance = previewArtifact?.lineage?.state === 'deleted'
    ? 'Original file was deleted; task snapshot retained.'
    : previewArtifact?.lineage?.state === 'moved'
      ? `Moved from ${previewArtifact.lineage.originPath} to ${previewArtifact.lineage.currentPath}.`
      : (previewArtifact?.review?.revisionCount ?? 0) > 0
        ? 'Task snapshot'
        : 'Current file preview';
  const resizeSession = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
    isActive: boolean;
  } | undefined>(undefined);
  const [isResizing, setIsResizing] = useState(false);
  const trayStyle = { '--detail-tray-width': `${trayWidth}px` } as CSSProperties;

  // Defensive cleanup: if the tray is closed/unmounted while a resize drag
  // is still active (its own pointerup never reaches `finishResize`), make
  // sure the host's suppression flag doesn't get stuck on forever.
  useEffect(() => {
    if (!isOpen && resizeSession.current) {
      logTrayDiagnostic('closed while resize session was active', {
        pointerId: resizeSession.current.pointerId,
        isActive: resizeSession.current.isActive,
      });
      resizeSession.current = undefined;
      setIsResizing(false);
      onResizingChange?.(false);
    }
  }, [isOpen, onResizingChange]);

  useEffect(() => () => {
    if (resizeSession.current) onResizingChange?.(false);
  }, [onResizingChange]);

  const resizeTray = (width: number) => {
    onTrayWidthChange(clampDetailTrayWidth(width));
  };

  const handleResizePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    resizeSession.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: trayWidth,
      isActive: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    // Suppress native window resizes starting from pointerdown, not from
    // the drag-activation threshold below. A resize that was already
    // queued (e.g. from opening the tray or switching to this preview a
    // moment earlier, throttled ~300ms out) can still fire in the gap
    // between pointerdown and the first RESIZE_ACTIVATION_DISTANCE_PX of
    // movement -- while the pointer is already captured on the handle --
    // which is enough on its own to corrupt the OS mouse-tracking loop and
    // produce the "collapses on immediate mousedown" symptom, with no
    // perceptible drag distance required to trigger it.
    onResizingChange?.(true);
  };

  const handleResizePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const session = resizeSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    const horizontalDistance = event.clientX - session.startX;
    if (!session.isActive) {
      if (Math.abs(horizontalDistance) < RESIZE_ACTIVATION_DISTANCE_PX) return;
      session.isActive = true;
      setIsResizing(true);
    }
    event.preventDefault();
    resizeTray(session.startWidth - horizontalDistance);
  };

  const finishResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const session = resizeSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    resizeSession.current = undefined;
    if (session.isActive) setIsResizing(false);
    onResizingChange?.(false);
  };

  const handleResizeKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      resizeTray(trayWidth + DETAIL_TRAY_KEYBOARD_STEP);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      resizeTray(trayWidth - DETAIL_TRAY_KEYBOARD_STEP);
    } else if (event.key === 'Home') {
      event.preventDefault();
      resizeTray(DETAIL_TRAY_MIN_WIDTH);
    }
  };

  if (!isOpen) return null;

  const isRunPanel = !detail || Boolean(previewArtifact);
  const close = () => {
    logTrayDiagnostic('header close callback', {
      isRunPanel,
      hasPreviewArtifact: Boolean(previewArtifact),
      hasDetail: Boolean(detail),
    });
    (isRunPanel ? onCloseRunPanel : onClose)();
  };
  const closePreview = () => {
    logTrayDiagnostic('preview close callback', {
      artifactId: previewArtifact?.artifactId,
    });
    onClosePreview();
  };
  const closeRunPanel = () => {
    logTrayDiagnostic('run panel close callback', {
      artifactId: previewArtifact?.artifactId,
    });
    onCloseRunPanel();
  };
  return (
    <aside
      className={`execution-detail-tray${isRunPanel ? ' execution-detail-tray--run-panel' : ''}${previewArtifact ? ' execution-detail-tray--preview' : !detail ? ' execution-detail-tray--run-card' : ''}${isResizing ? ' execution-detail-tray--resizing' : ''}`}
      style={trayStyle}
      data-presence-phase={presencePhase}
      aria-hidden={presencePhase !== 'present'}
      inert={presencePhase !== 'present' ? '' : undefined}
      onTransitionEnd={onPresenceTransitionEnd}
    >
      <div
        className="detail-tray-resize-handle"
        role="separator"
        tabIndex={0}
        aria-label="Resize run panel"
        aria-orientation="vertical"
        aria-valuemin={DETAIL_TRAY_MIN_WIDTH}
        aria-valuenow={trayWidth}
        onPointerDown={handleResizePointerDown}
        onPointerMove={handleResizePointerMove}
        onPointerUp={finishResize}
        onPointerCancel={finishResize}
        onLostPointerCapture={finishResize}
        onKeyDown={handleResizeKeyDown}
      />
      {previewArtifact ? (
        <div className="tray-artifact-preview-topbar">
          <div className="tray-artifact-preview-panel-actions">
            <button type="button" className="tray-artifact-preview-close" onClick={closePreview} aria-label="Close preview" title="Close preview"><PreviewActionIcon action="close-preview" /></button>
            <button type="button" className="tray-artifact-preview-close" onClick={closeRunPanel} aria-label="Collapse run panel" title="Collapse run panel"><PreviewActionIcon action="collapse-panel" /></button>
          </div>
          {previewArtifact.group === 'produced' && (
            <ArtifactReviewDocumentTabs
              artifacts={artifacts.produced}
              activeArtifactId={previewArtifact.artifactId}
              onSelectArtifact={onPreviewArtifact}
            />
          )}
        </div>
      ) : (
        <div className="detail-tray-header">
          <div>
            {detail && (
              <div className="detail-tray-eyebrow">
                {formatDetailKind(detail.detail_kind)}
                {detail.streaming ? <span className="detail-tray-live">Live</span> : null}
              </div>
            )}
            <div className="detail-tray-title">
              {!detail ? 'Run overview' : detail.summary || 'Execution detail'}
            </div>
          </div>
          <div className="detail-tray-header-actions">
            <button
              type="button"
              className={isRunPanel ? 'tray-artifact-preview-close' : 'detail-tray-close'}
              onClick={close}
              aria-label={isRunPanel ? 'Collapse run panel' : 'Close detail tray'}
              title={isRunPanel ? 'Collapse run panel' : undefined}
            >
              {isRunPanel ? <PreviewActionIcon action="collapse-panel" /> : '×'}
            </button>
          </div>
        </div>
      )}

      {detail && !previewArtifact && (
        <div className="detail-tray-follow-row">
          <span>{followLatest ? 'Following latest' : 'Pinned to selected step'}</span>
          {hasNewerDetail && (
            <button className="detail-tray-link" onClick={onJumpToLatest}>
              Jump to latest
            </button>
          )}
        </div>
      )}

      {previewArtifact ? (
        <div className="detail-tray-content tray-artifact-preview">
          <div className="tray-artifact-preview-document-header">
            <div className="tray-artifact-preview-document-identity">
              <div className="detail-tray-eyebrow">Document preview</div>
              <div className="detail-tray-title" title={previewArtifact.displayName}>{previewArtifact.displayName}</div>
              <p className="tray-artifact-preview-provenance">{previewProvenance}</p>
            </div>
            <ArtifactPreviewActionBar
              artifact={previewArtifact}
              agentTaskId={agentTaskId}
              rootTaskId={rootTaskId}
              isCurrentFileAvailable={isPreviewArtifactFileAvailable}
              renderIcon={action => <PreviewActionIcon action={action} />}
            />
          </div>
          {previewArtifact.group === 'produced' ? (
            <ArtifactReviewWorkspace
              key={`${previewArtifact.artifactId}:${previewArtifact.localPath ?? ''}`}
              agentTaskId={agentTaskId}
              rootTaskId={rootTaskId}
              focusedRunId={focusedRunId}
              artifacts={artifacts.produced}
              activeArtifactId={previewArtifact.artifactId}
              onSelectArtifact={onPreviewArtifact}
              showDocumentTabs={false}
              previewTransport={agentTaskArtifactPreviewTransport}
              runs={runs}
              subscribeToEvents={subscribeToAgentTaskEvents}
            />
          ) : (
            <InlineArtifactPreview
              key={`${previewArtifact.artifactId}:${previewArtifact.localPath ?? ''}`}
              artifact={previewArtifact}
              presentation="tray"
              transport={agentTaskArtifactPreviewTransport}
              agentTaskId={agentTaskId}
              rootTaskId={rootTaskId}
              subscribeToEvents={subscribeToAgentTaskEvents}
            />
          )}
        </div>
      ) : detail ? (
        <div className="detail-tray-content">
          {detail.timestamp && (
            <div className="detail-tray-timestamp">
              {new Date(detail.timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}
            </div>
          )}
          {detail.artifact ? (
            <ArtifactDetail artifact={detail.artifact} onPreviewArtifact={onPreviewArtifact} />
          ) : (
            <>
              {renderMetadata(detail.metadata)}
              <div className="detail-tray-body">
                <MarkdownRenderer content={formatted.userMarkdown} />
              </div>
              {formatted.raw && (
                <div className="detail-tray-raw">
                  <button
                    className="detail-tray-link"
                    onClick={() => setShowRaw(v => !v)}
                  >
                    {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
                  </button>
                  {showRaw && (
                    <pre className="detail-tray-raw-json">
                      {formatted.raw}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          <AgentRunHistoryTray
            runs={runs}
            focusedRunId={focusedRunId}
            onSelect={onFocusRun}
          />
          <RunCard
            artifacts={artifacts}
            presentation={overviewPresentation || deriveAgentRunOverviewPresentation(
              runPresentation || deriveAgentRunPresentation(timeline, terminalStatus, isProcessing),
            )}
            isProcessing={isProcessing}
            onPreviewArtifact={onPreviewArtifact}
          />
        </>
      )}
    </aside>
  );
}
