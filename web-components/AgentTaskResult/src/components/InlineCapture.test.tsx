// @vitest-environment jsdom

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import InlineCapture from './InlineCapture';
import type { CaptureStateMessage } from '../types';

vi.mock('../services/bridge', () => ({
  stopFollowUpCapture: vi.fn(),
  cancelFollowUpCapture: vi.fn(),
  stopNewAgentTaskCapture: vi.fn(),
  cancelNewAgentTaskCapture: vi.fn(),
  stopRefinementRecording: vi.fn(),
}));

// The component now reads the live meter level from the shared store instead
// of `captureState.audioLevel` (see captureMeterStore.ts), so tests control
// the level through this mock rather than the CaptureStateMessage fixture.
const { useCaptureMeter } = vi.hoisted(() => ({
  useCaptureMeter: vi.fn(() => 0),
}));

vi.mock('../store/captureMeterStore', () => ({
  useCaptureMeter,
}));

// Spies on the audioLevel AnimatedBubble actually receives, while still
// rendering the real component underneath so the existing canvas-vs-svg
// regression assertions below keep exercising real markup.
const { animatedBubbleProps } = vi.hoisted(() => ({
  animatedBubbleProps: vi.fn(),
}));

vi.mock('../../../shared/bubble/AnimatedBubble', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../shared/bubble/AnimatedBubble')>();
  const RealAnimatedBubble = actual.default;
  return {
    ...actual,
    default: (props: Parameters<typeof RealAnimatedBubble>[0]) => {
      animatedBubbleProps(props);
      return <RealAnimatedBubble {...props} />;
    },
  };
});

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  useCaptureMeter.mockReset();
  useCaptureMeter.mockReturnValue(0);
  animatedBubbleProps.mockClear();
  vi.restoreAllMocks();
});

function render(captureState: CaptureStateMessage) {
  act(() => {
    root = createRoot(container);
    root.render(<InlineCapture captureState={captureState} />);
  });
}

describe('InlineCapture', () => {
  it('renders nothing when not capturing (regression: existing early-return guard)', () => {
    render({ type: 'followUp', isCapturing: false, wordsDetected: '', audioLevel: 0, silenceProgress: 0 });
    expect(container.innerHTML).toBe('');
  });

  it('renders an animated bubble canvas instead of the static mic glyph while capturing (Finding F1 repair)', () => {
    render({ type: 'followUp', isCapturing: true, wordsDetected: 'schedule a meeting', audioLevel: 0.4, silenceProgress: 0 });
    const mic = container.querySelector('.inline-capture-mic');
    expect(mic).not.toBeNull();
    expect(mic!.querySelector('canvas')).not.toBeNull();
    expect(mic!.querySelector('svg')).toBeNull();
  });

  it('reads the live level from the shared capture-meter store rather than the captureState field (Package 1 regression)', () => {
    useCaptureMeter.mockReturnValue(0.75);
    // captureState.audioLevel is deliberately different from the store's
    // mocked value -- if the component regressed to reading the field
    // directly, this assertion would fail.
    render({ type: 'followUp', isCapturing: true, wordsDetected: '', audioLevel: 0.1, silenceProgress: 0 });

    expect(animatedBubbleProps).toHaveBeenCalledWith(
      expect.objectContaining({ audioLevel: 0.75 }),
    );
  });

  it('renders the follow-up/new-AgentTask/refinement labels unchanged (regression check)', () => {
    render({ type: 'followUp', isCapturing: true, wordsDetected: '', audioLevel: 0, silenceProgress: 0 });
    expect(container.textContent).toContain('Listening for follow-up AgentTask...');

    render({ type: 'newAgentTask', isCapturing: true, wordsDetected: '', audioLevel: 0, silenceProgress: 0 });
    expect(container.textContent).toContain('Recording new AgentTask...');

    render({ type: 'refinement', isCapturing: true, wordsDetected: '', audioLevel: 0, silenceProgress: 0 });
    expect(container.textContent).toContain('Recording refinement...');
  });

  it('renders detected words only when non-empty (regression check on the existing conditional)', () => {
    render({ type: 'followUp', isCapturing: true, wordsDetected: '', audioLevel: 0, silenceProgress: 0 });
    expect(container.querySelector('.inline-capture-words')).toBeNull();

    render({ type: 'followUp', isCapturing: true, wordsDetected: 'schedule a meeting', audioLevel: 0, silenceProgress: 0 });
    expect(container.querySelector('.inline-capture-words')?.textContent).toBe('schedule a meeting');
  });
});
