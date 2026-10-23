import AnimatedBubble from '../../../shared/bubble/AnimatedBubble';
import { WindowControlButton } from '@shared/WindowControlButton';
import paprikaIcon from '../assets/paprika-icon.png';
import { BASIL_TEAM } from '../copy/teamIdentity';
import { closeWidget, minimizeWidget } from '../services/bridge';
import type { BubbleMode } from '../types';
import { normalizeProgressStepText } from './result/progressStepText';
import { StopAction } from '../../../shared/StopAction';
import { plainMarkdownText } from '../../../shared/plainMarkdownText';
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
  isCanceling?: boolean;
  onCancelRunning?: () => void;
  canCollapse?: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  collapsedTaskTitle?: string;
  collapsedStatusText?: string;
  isAwaitingInput?: boolean;
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
  isCanceling = false,
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
  const normalizedCollapsedTaskTitle = isCollapsed
    ? plainMarkdownText(collapsedTaskTitle) || null
    : null;
  const embeddedTaskTitle = plainMarkdownText(taskTitle);

  if (embedded) {
    return (
      <div className="embedded-task-toolbar">
        <span className="embedded-task-toolbar-title">{embeddedTaskTitle || BASIL_TEAM.agentTask.displayName}</span>
        {showCancelStop && onCancelRunning ? (
          <StopAction
            className="agent-task-stop-action"
            isStopping={isCanceling}
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
              <WindowControlButton kind="close" label="Close" className="header-btn" onClick={closeWidget} />
              <WindowControlButton kind="minimize" label="Minimize" className="header-btn" onClick={minimizeWidget} />
            </>
          )}
          {canCollapse && onToggleCollapse && (
            <WindowControlButton
              kind="collapse"
              label={isCollapsed ? 'Expand results' : 'Collapse results'}
              className="header-btn"
              collapsed={isCollapsed}
              onClick={onToggleCollapse}
            />
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
        className={`header-right${showCancelStop && onCancelRunning ? ' has-stop-action' : ''}${isCanceling ? ' is-stopping' : ''}`}
        data-agent-task-header-bubble
      >
        {showCancelStop && onCancelRunning && (
          <StopAction
            className="agent-task-stop-action"
            isStopping={isCanceling}
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
