import AnimatedBubble from './AnimatedBubble';
import paprikaIcon from '../assets/paprika-icon.png';
import { BASIL_TEAM } from '../copy/teamIdentity';
import { closeWidget, minimizeWidget } from '../services/bridge';
import type { BubbleMode } from '../types';
import { normalizeProgressStepText } from './result/progressStepText';
import { StopAction } from '../../../shared/StopAction';
import { useCaptureMeter } from '../store/captureMeterStore';

interface Props {
  isProcessing: boolean;
  isCapturing: boolean;
  bubbleMode: BubbleMode;
  baseColor: string;
  accentColor: string;
  showCancelStop?: boolean;
  hideWindowControls?: boolean;
  embedded?: boolean;
  taskTitle?: string;
  isCancelling?: boolean;
  onCancelRunning?: () => void;
  canCollapse?: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  collapsedTaskTitle?: string;
  collapsedStatusText?: string;
  isAwaitingInput?: boolean;
}

function plainEmbeddedTaskTitle(markdown: string | undefined): string {
  return (markdown || '')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/(`{1,3})([\s\S]*?)\1/g, '$2')
    .replace(/(\*\*|__|~~)([\s\S]*?)\1/g, '$2')
    .replace(/(^|[^\\])([*_])([^*_]+)\2/g, '$1$3')
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s?|[-+*]\s+|\d+\.\s+|\[[ xX]\]\s+)/gm, '')
    .replace(/\\([\\`*_{}[\]()#+\-.!])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export default function Header({
  isProcessing,
  isCapturing,
  bubbleMode,
  // baseColor / accentColor are kept on the Props interface for source
  // compatibility with existing callers (App.tsx still supplies them) but
  // are intentionally unconsumed now: every bubble state resolves to a
  // CSS variable below. Aliased to underscore-prefixed names so
  // tsconfig's `noUnusedParameters` is satisfied without changing the
  // public prop shape.
  baseColor: _baseColor,
  accentColor: _accentColor,
  showCancelStop = false,
  hideWindowControls = false,
  embedded = false,
  taskTitle,
  isCancelling = false,
  onCancelRunning,
  canCollapse = false,
  isCollapsed = false,
  onToggleCollapse,
  collapsedTaskTitle,
  collapsedStatusText,
  isAwaitingInput = false,
}: Props) {
  const audioLevel = useCaptureMeter();
  const effectiveMode: BubbleMode = isCapturing
    ? 'audioResponsive'
    : isAwaitingInput || isProcessing
      ? 'processing'
      : bubbleMode;

  // Pull state colors from CSS variables so they stay in sync with the
  // centralized AestheticSystem palette:
  //   - red for recording
  //   - yellow for user input requests
  //   - Royal Purple for processing
  //   - ready green for the non-capturing/non-processing resting state
  // The variables are defined in theme.css and overridden by App.tsx when
  // the Swift host pushes a new theme payload (only --recording-* and
  // --processing-* are forwarded; --ready-* is fixed and lives in CSS).
  //
  // The `baseColor` / `accentColor` props are retained for source
  // compatibility with callers but are no longer consumed here; every
  // branch now resolves to a CSS variable so the three bubble states stay
  // semantically aligned across React and native surfaces.
  const effectiveBase = isCapturing
    ? 'var(--recording-base)'
    : isAwaitingInput
      ? 'var(--warning-base)'
      : isProcessing
      ? 'var(--processing-base)'
      : 'var(--ready-base)';

  const effectiveAccent = isCapturing
    ? 'var(--recording-accent)'
    : isAwaitingInput
      ? '#FFFFFF'
      : isProcessing
      ? 'var(--processing-accent)'
      : 'var(--ready-accent)';
  // Deepen every processing-mode accent toward its semantic base color so purple and amber retain their hue; this stays in JS because WebKit does not resolve color-mix through the getComputedStyle probe.
  const accentDeepenTowardBase = effectiveMode === 'processing' ? 0.55 : 0;
  const normalizedCollapsedStatus = isCollapsed && collapsedStatusText?.trim()
    ? normalizeProgressStepText(collapsedStatusText).trim()
    : null;
  const normalizedCollapsedTaskTitle = isCollapsed && collapsedTaskTitle?.trim()
    ? collapsedTaskTitle.trim()
    : null;
  const embeddedTaskTitle = plainEmbeddedTaskTitle(taskTitle);

  if (embedded) {
    return (
      <div className="embedded-task-toolbar">
        <span className="embedded-task-toolbar-title">{embeddedTaskTitle || BASIL_TEAM.agentTask.displayName}</span>
        {showCancelStop && onCancelRunning ? (
          <StopAction
            className="agent-task-stop-action"
            isStopping={isCancelling}
            onStop={onCancelRunning}
            title="Stop the running request"
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className="widget-header">
      <div className="header-left">
        <div className="header-controls" data-agent-task-header-controls>
          {!hideWindowControls && (
            <>
              <button className="header-btn" onClick={closeWidget} title="Close">
          <svg width="20" height="20" viewBox="0 0 22 22">
            <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
            <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
            <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          </button>
          <button className="header-btn" onClick={minimizeWidget} title="Minimize">
          <svg width="20" height="20" viewBox="0 0 22 22">
            <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
            <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          </button>
            </>
          )}
          {canCollapse && onToggleCollapse && (
            <button
            className="header-btn"
            onClick={onToggleCollapse}
            title={isCollapsed ? 'Expand results' : 'Collapse results'}
            aria-label={isCollapsed ? 'Expand results' : 'Collapse results'}
            >
            <svg width="20" height="20" viewBox="0 0 22 22">
              <circle cx="11" cy="11" r="10" fill="rgba(51,85,155,0.15)" />
              <path
                className={`header-collapse-chevron ${isCollapsed ? 'collapsed' : ''}`}
                d="M7 9l4 4 4-4"
                fill="none"
                stroke="var(--secondary)"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            </button>
          )}
          <img className="header-team-icon" src={paprikaIcon} alt="" aria-hidden="true" />
        </div>
        <div className="header-identity" data-agent-task-header-identity>
          <span className="header-title">{BASIL_TEAM.agentTask.displayName}</span>
          {normalizedCollapsedTaskTitle && (
            <span className="header-collapsed-task-title">{normalizedCollapsedTaskTitle}</span>
          )}
          {normalizedCollapsedStatus && (
            <span className="header-collapsed-status">{normalizedCollapsedStatus}</span>
          )}
        </div>
      </div>
      <div
        className={`header-right${showCancelStop && onCancelRunning ? ' has-stop-action' : ''}${isCancelling ? ' is-stopping' : ''}`}
        data-agent-task-header-bubble
      >
        {showCancelStop && onCancelRunning && (
          <StopAction
            className="agent-task-stop-action"
            isStopping={isCancelling}
            onStop={onCancelRunning}
            title="Stop the running request"
          />
        )}
        <div className="header-bubble">
          <AnimatedBubble
            size={44}
            mode={effectiveMode}
            baseColor={effectiveBase}
            accentColor={effectiveAccent}
            accentDeepen={accentDeepenTowardBase}
            audioLevel={audioLevel}
          />
        </div>
      </div>
    </div>
  );
}
