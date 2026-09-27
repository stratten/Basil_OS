import type { AssistantSessionState } from '../state/assistantSessionReducer';
import type { WidgetPhase } from './widgetPhase';

export interface WidgetSize {
  width: number;
  height: number;
}

export function deriveWidgetSize(state: AssistantSessionState, phase: WidgetPhase): WidgetSize {
  if (phase === 'typedInput') return { width: 550, height: 420 };
  if (phase !== 'result') return { width: 260, height: 120 };
  if (state.isResultChromeCollapsed) return { width: 260, height: 87 };
  if (!state.shouldPersistUI) return { width: 450, height: 220 };

  return {
    width: 520,
    height: 250,
  };
}
