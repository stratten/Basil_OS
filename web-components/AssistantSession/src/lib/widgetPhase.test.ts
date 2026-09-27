import { describe, expect, it } from 'vitest';
import { deriveWidgetPhase } from './widgetPhase';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';

describe('deriveWidgetPhase', () => {
  it('shows result as soon as assistantOutput is nonempty, even while processing', () => {
    const phase = deriveWidgetPhase({
      ...initialAssistantSessionState,
      assistantOutput: 'partial',
      assistantSessionStatus: 'running',
    });
    expect(phase).toBe('result');
  });

  it('shows processing when any status failed and there is no output', () => {
    expect(
      deriveWidgetPhase({ ...initialAssistantSessionState, assistantSessionStatus: 'failed' }),
    ).toBe('processing');
    expect(deriveWidgetPhase({ ...initialAssistantSessionState, ocrStatus: 'failed' })).toBe('processing');
    expect(
      deriveWidgetPhase({ ...initialAssistantSessionState, transcriptionStatus: 'failed' }),
    ).toBe('processing');
  });

  it('stays in the input slot while uncommitted even if OCR is running', () => {
    expect(
      deriveWidgetPhase({
        ...initialAssistantSessionState,
        ocrStatus: 'running',
        inputCommitted: false,
        inputMode: 'speak',
      }),
    ).toBe('recording');
    expect(
      deriveWidgetPhase({
        ...initialAssistantSessionState,
        ocrStatus: 'running',
        inputCommitted: false,
        inputMode: 'type',
      }),
    ).toBe('typedInput');
  });

  it('shows processing after commit when there is no output yet', () => {
    expect(
      deriveWidgetPhase({
        ...initialAssistantSessionState,
        inputCommitted: true,
        assistantSessionStatus: 'running',
      }),
    ).toBe('processing');
  });
});
