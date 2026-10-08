import AnimatedBubble from '../../../shared/bubble/AnimatedBubble';
import { WindowControlButton } from '@shared/WindowControlButton';
import { cancelOperation, enterTypedRefinement, minimizeWidget, openHistory, switchInputMode, toggleResultCollapse } from '../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../state/assistantSessionReducer';
import type { AssistantSessionThemePayload } from '../bridge/types';
import type { WidgetPhase } from '../lib/widgetPhase';
import { NativeSymbol } from './NativeSymbol';
import { useAssistantSessionMeter } from './useAssistantSessionMeter';

export function Header({
  state,
  theme,
  phase,
  showProgressElements,
  onSwitchToTypedRefinement,
}: {
  state: AssistantSessionState;
  theme: AssistantSessionThemePayload;
  phase: WidgetPhase;
  showProgressElements: boolean;
  onSwitchToTypedRefinement?: () => void;
}) {
  const meterLevel = useAssistantSessionMeter();
  const isRefinementRecording =
    state.isRefinementMode &&
    (state.isRecording || state.transcriptionStatus === 'running') &&
    state.assistantSessionStatus !== 'running';
  const modalityMutable = !state.inputCommitted && phase !== 'result';
  const showResultCollapse = phase === 'result';

  return (
    <div className="assistant-session-header">
      <div className="assistant-session-header__left">
        <button type="button" className="assistant-session-header__traffic" title="Cancel request" aria-label="Cancel request" onClick={cancelOperation}>
          <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
            <circle cx="11" cy="11" r="10" fill="color-mix(in srgb, var(--secondary, #4c7bf0) 15%, transparent)" />
            <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary, #4c7bf0)" strokeWidth="1.6" strokeLinecap="round" />
            <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary, #4c7bf0)" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <WindowControlButton kind="minimize" label="Minimize" className="assistant-session-header__traffic" onClick={minimizeWidget} />
        {showResultCollapse && (
          <WindowControlButton
            kind="collapse"
            label={state.isResultChromeCollapsed ? 'Expand results' : 'Collapse results'}
            className="assistant-session-header__traffic"
            collapsed={state.isResultChromeCollapsed}
            pressed={state.isResultChromeCollapsed}
            onClick={toggleResultCollapse}
          />
        )}
        <button type="button" className="assistant-session-header__ghost-btn" title="Open history" aria-label="Open history" onClick={openHistory}>
          <NativeSymbol name="history" size={10} />
        </button>
        {isRefinementRecording ? (
          <button
            type="button"
            className="assistant-session-header__ghost-btn"
            title="Switch to typed refinement"
            onClick={() => {
              enterTypedRefinement();
              onSwitchToTypedRefinement?.();
            }}
          >
            <NativeSymbol name="keyboard" size={10} />
          </button>
        ) : modalityMutable && (
          <button
            type="button"
            className="assistant-session-header__ghost-btn"
            title={state.inputMode === 'type' ? 'Switch to voice entry' : 'Switch to text entry'}
            onClick={() => switchInputMode(state.inputMode === 'speak' ? 'type' : 'speak')}
          >
            <NativeSymbol name={state.inputMode === 'type' ? 'mic' : 'keyboard'} size={10} />
          </button>
        )}
        {showProgressElements && state.isRecording && (
          <NativeSymbol name="micFill" size={10} className="assistant-session-header__mic-live" />
        )}
        <img className="assistant-session-header__dill" src={new URL('../../../shared/assets/native-symbols/dill-icon.png', import.meta.url).href} alt="" />
        <span className="assistant-session-header__title">Dill</span>
      </div>
      <div className="assistant-session-header__bubble">
        <AnimatedBubble
          size={44}
          mode={state.bubbleMode}
          audioLevel={meterLevel}
          baseColor={state.bubbleColors.base || theme.readyBase}
          accentColor={state.bubbleColors.accent || theme.readyAccent}
        />
      </div>
    </div>
  );
}
