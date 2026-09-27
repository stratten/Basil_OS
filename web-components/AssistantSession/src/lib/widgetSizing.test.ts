import { describe, expect, it } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { deriveWidgetSize } from './widgetSizing';

describe('deriveWidgetSize', () => {
  it('uses the exact compact and typed-input sizes', () => {
    expect(deriveWidgetSize(initialAssistantSessionState, 'recording')).toEqual({ width: 260, height: 120 });
    expect(deriveWidgetSize(initialAssistantSessionState, 'processing')).toEqual({ width: 260, height: 120 });
    expect(deriveWidgetSize(initialAssistantSessionState, 'typedInput')).toEqual({ width: 550, height: 420 });
  });

  it('uses the exact collapsed and nonpersistent result sizes', () => {
    expect(deriveWidgetSize(
      { ...initialAssistantSessionState, isResultChromeCollapsed: true },
      'result',
    )).toEqual({ width: 260, height: 87 });
    expect(deriveWidgetSize(initialAssistantSessionState, 'result')).toEqual({ width: 450, height: 220 });
  });

  it('uses a stable initial persistent-result size before rendered-content measurement', () => {
    expect(deriveWidgetSize(
      { ...initialAssistantSessionState, shouldPersistUI: true, assistantOutput: 'short' },
      'result',
    )).toEqual({ width: 520, height: 250 });
    expect(deriveWidgetSize(
      { ...initialAssistantSessionState, shouldPersistUI: true, assistantOutput: 'x'.repeat(10_000) },
      'result',
    )).toEqual({ width: 520, height: 250 });
  });
});
