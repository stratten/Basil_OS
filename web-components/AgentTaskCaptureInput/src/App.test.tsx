// @vitest-environment jsdom

import { describe, expect, it, beforeEach, afterEach, vi, type Mock } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import App from './App';
import type { CaptureInputMessage } from './types';
import {
  baseTextSnapshot,
  baseVoiceSnapshot,
  buildInitMessage,
  sampleReferencePaths,
  voiceRecordingSnapshot,
  withReferencePaths,
} from './fixtures/captureFixtures';

vi.mock('../../shared/bubble/AnimatedBubble', () => ({
  default: () => <canvas data-testid="animated-bubble" />,
}));

vi.mock('./components/CaptureModelPickerMenu', () => ({
  default: ({
    variant = 'default',
    onModelChange,
    onRequestNativeMenu,
  }: {
    variant?: 'default' | 'miniChevron';
    onModelChange: (modelId: string | null) => void;
    onRequestNativeMenu?: (
      models: Array<{ id: string; display_name: string; category: 'local' | 'api' | 'custom' }>,
      selectedModelId: string | null,
      anchorRect: DOMRect,
    ) => void;
  }) => (
    <button
      type="button"
      aria-label="Reasoning model"
      data-picker-variant={variant}
      data-native-menu={onRequestNativeMenu ? 'true' : 'false'}
      onClick={() => {
        if (onRequestNativeMenu) {
          onRequestNativeMenu(
            [{ id: 'reasoning-model-123', display_name: 'Reasoning Model', category: 'local' }],
            'reasoning-model-123',
            { x: 134, y: 161, width: 14, height: 14 } as DOMRect,
          );
          return;
        }
        onModelChange('reasoning-model-123');
      }}
    >
      Model
    </button>
  ),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
let postMessage: Mock<(message: CaptureInputMessage) => void>;

beforeEach(() => {
  postMessage = vi.fn<(message: CaptureInputMessage) => void>();
  window.webkit = { messageHandlers: { agentTaskCaptureBridge: { postMessage } } };
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    root = createRoot(container);
    root.render(<App />);
  });
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
});

function hydrate(snapshot: ReturnType<typeof baseVoiceSnapshot>): void {
  act(() => {
    window.basilAgentTaskCapture!.onInit(buildInitMessage(snapshot));
  });
}

describe('App', () => {
  it('renders the voice capture surface before any reference-path content when in voice mode', () => {
    hydrate(voiceRecordingSnapshot);
    expect(container.querySelector('.voice-capture-body')).not.toBeNull();
    expect(container.querySelector('.text-capture-body')).toBeNull();
    expect(container.textContent).toContain('Listening...');
    expect(container.textContent).toContain('Paprika');
    expect(container.textContent).not.toContain('Basil');
    expect(container.querySelector('[data-picker-variant="miniChevron"][data-native-menu="true"]')).not.toBeNull();
  });

  it('renders the text capture surface when the snapshot reports text modality', () => {
    hydrate(baseTextSnapshot());
    expect(container.querySelector('.text-capture-body')).not.toBeNull();
    expect(container.querySelector('.voice-capture-body')).toBeNull();
    expect(container.querySelector('[data-picker-variant="default"][data-native-menu="true"]')).not.toBeNull();
  });

  it('forwards a voice model choice through the native-menu bridge', () => {
    hydrate(baseVoiceSnapshot());

    act(() => {
      (container.querySelector('[aria-label="Reasoning model"]') as HTMLButtonElement).click();
    });

    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'showNativeModelPicker',
      models: [{ id: 'reasoning-model-123', displayName: 'Reasoning Model', category: 'local' }],
      selectedModelId: 'reasoning-model-123',
      anchorRect: { x: 134, y: 161, width: 14, height: 14 },
    });
  });

  it('switches surfaces live when a later onSnapshot changes modality (mode-switch row, Package 4)', () => {
    hydrate(baseVoiceSnapshot());
    expect(container.querySelector('.voice-capture-body')).not.toBeNull();

    act(() => {
      window.basilAgentTaskCapture!.onSnapshot(baseTextSnapshot({ revision: 999 }));
    });

    expect(container.querySelector('.text-capture-body')).not.toBeNull();
    expect(container.querySelector('.voice-capture-body')).toBeNull();
  });

  it('renders the reference paths list only when references are present (empty-state row, Package 4)', () => {
    hydrate(baseVoiceSnapshot());
    expect(container.querySelector('.reference-paths-list')).toBeNull();

    act(() => {
      window.basilAgentTaskCapture!.onSnapshot(
        withReferencePaths(baseVoiceSnapshot({ revision: 1000 }), sampleReferencePaths)
      );
    });

    expect(container.querySelector('.reference-paths-list')).not.toBeNull();
    expect(container.textContent).toContain('Q3-report.pdf');
    expect(container.textContent).toContain('project-assets');
  });

  it('renders the drop-zone overlay only while a native file drag is over the widget (drag-over row, Package 4)', () => {
    // `isDraggingOver` is owned entirely by this component via plain DOM
    // drag events (mirroring `TextFollowUp.tsx`'s established pattern) —
    // see `App.tsx`'s `handleDragOver`/`handleDragLeave`/`handleDrop`. It is
    // no longer read from the native snapshot.
    hydrate(baseVoiceSnapshot());
    expect(container.querySelector('.capture-drop-overlay')).toBeNull();

    const widget = container.querySelector('.capture-widget') as HTMLElement;

    act(() => {
      widget.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    expect(container.querySelector('.capture-drop-overlay')).not.toBeNull();

    act(() => {
      widget.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    });
    expect(container.querySelector('.capture-drop-overlay')).toBeNull();
  });

  it('renders the loading frame with no content before the first onInit (cold-load row, Package 4)', () => {
    // A fresh App instance that has not yet received onInit in this test.
    const freshContainer = document.createElement('div');
    document.body.appendChild(freshContainer);
    let freshRoot: Root;
    act(() => {
      freshRoot = createRoot(freshContainer);
      freshRoot.render(<App />);
    });
    expect(freshContainer.querySelector('.capture-widget--loading')).not.toBeNull();
    expect(freshContainer.querySelector('.voice-capture-body')).toBeNull();
    act(() => {
      freshRoot.unmount();
    });
    freshContainer.remove();
  });

  it('renders fallback timer and configured completion hotkey when intelligent capture is disabled', () => {
    hydrate(baseVoiceSnapshot({
      isCapturing: true,
      useIntelligentCapture: false,
      remainingSeconds: 7,
      progressPercentage: 0.7,
      agentTaskHotkeyDisplay: '⌥P',
    }));

    expect(container.querySelector('.voice-capture-body__timer')?.textContent).toBe('7');
    expect(container.textContent).toContain('Press ⌥P when done');
  });
});
