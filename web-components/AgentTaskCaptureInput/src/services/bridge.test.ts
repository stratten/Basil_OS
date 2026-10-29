// @vitest-environment jsdom

import { describe, expect, it, vi, beforeEach } from 'vitest';
import {
  cancelCapture,
  enterTextEntryMode,
  enterVoiceMode,
  openReferencePath,
  pickReferenceFiles,
  registerAudioLevelHandler,
  registerFontsHandler,
  registerInitHandler,
  registerSnapshotHandler,
  registerThemeHandler,
  removeReferencePath,
  requestCaptureResize,
  requestSnapshot,
  sendCaptureInputReady,
  setSelectedModel,
  showNativeModelPicker,
  showHistory,
  submitTextPrompt,
  updateTextDraft,
} from './bridge';
import { baseVoiceSnapshot, buildInitMessage, sampleFonts, sampleTheme } from '../fixtures/captureFixtures';

function installPostMessageSpy(): ReturnType<typeof vi.fn> {
  const postMessage = vi.fn();
  window.webkit = { messageHandlers: { agentTaskCaptureBridge: { postMessage } } };
  return postMessage;
}

describe('outgoing capture intents', () => {
  beforeEach(() => {
    installPostMessageSpy();
  });

  it('posts every exported intent with its exact wire shape', () => {
    const postMessage = window.webkit!.messageHandlers.agentTaskCaptureBridge!.postMessage as ReturnType<typeof vi.fn>;

    sendCaptureInputReady();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'captureInputReady' });

    requestSnapshot();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'requestSnapshot' });

    requestCaptureResize(360, 280);
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'requestCaptureResize', width: 360, height: 280 });

    enterVoiceMode();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'enterVoiceMode' });

    enterTextEntryMode();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'enterTextEntryMode' });

    updateTextDraft('hello world');
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'updateTextDraft', text: 'hello world' });

    submitTextPrompt('hello world', 'gpt-5.6-terra-high');
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'submitTextPrompt',
      text: 'hello world',
      modelId: 'gpt-5.6-terra-high',
    });

    submitTextPrompt('no model chosen yet');
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'submitTextPrompt',
      text: 'no model chosen yet',
      modelId: undefined,
    });

    setSelectedModel('reasoning-model-123');
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'setSelectedModel',
      modelId: 'reasoning-model-123',
    });

    setSelectedModel(null);
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'setSelectedModel',
      modelId: null,
    });

    showNativeModelPicker(
      [{ id: 'local-reasoning', displayName: 'Local Reasoning', category: 'local' }],
      'local-reasoning',
      { x: 134, y: 161, width: 14, height: 14 },
    );
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'showNativeModelPicker',
      models: [{ id: 'local-reasoning', displayName: 'Local Reasoning', category: 'local' }],
      selectedModelId: 'local-reasoning',
      anchorRect: { x: 134, y: 161, width: 14, height: 14 },
    });

    cancelCapture();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'cancelCapture' });

    pickReferenceFiles();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'pickReferenceFiles' });

    removeReferencePath(2);
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'removeReferencePath', index: 2 });

    openReferencePath('/Users/basil-user/Documents/Q3-report.pdf');
    expect(postMessage).toHaveBeenLastCalledWith({
      type: 'openReferencePath',
      path: '/Users/basil-user/Documents/Q3-report.pdf',
    });

    showHistory();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'showHistory' });
  });

  it('logs to console instead of throwing when no Swift handler is installed (adversarial: missing host)', () => {
    window.webkit = undefined;
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    expect(() => cancelCapture()).not.toThrow();
    expect(consoleSpy).toHaveBeenCalledWith('[AgentTaskCaptureInput] No Swift handler, message:', { type: 'cancelCapture' });
    consoleSpy.mockRestore();
  });
});

describe('incoming capture messages', () => {
  beforeEach(() => {
    installPostMessageSpy();
  });

  it('routes onInit to the registered init handler exactly once per call', () => {
    const initHandler = vi.fn();
    registerInitHandler(initHandler);
    const snapshot = baseVoiceSnapshot();
    const initMessage = buildInitMessage(snapshot);

    window.basilAgentTaskCapture!.onInit(initMessage);

    expect(initHandler).toHaveBeenCalledTimes(1);
    expect(initHandler).toHaveBeenCalledWith(initMessage);
  });

  it('applies an in-order onSnapshot and drops a stale/out-of-order one (adversarial: malformed/out-of-order revision)', () => {
    const snapshotHandler = vi.fn();
    registerSnapshotHandler(snapshotHandler);
    const first = baseVoiceSnapshot({ revision: 5, statusMessage: 'Listening...' });
    window.basilAgentTaskCapture!.onInit(buildInitMessage(first, 51823));

    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const stale = baseVoiceSnapshot({ revision: 5, statusMessage: 'Stale duplicate' });
    window.basilAgentTaskCapture!.onSnapshot(stale);
    expect(snapshotHandler).not.toHaveBeenCalled();
    expect(consoleWarnSpy).toHaveBeenCalled();

    const next = baseVoiceSnapshot({ revision: 6, statusMessage: 'Processing...' });
    window.basilAgentTaskCapture!.onSnapshot(next);
    expect(snapshotHandler).toHaveBeenCalledWith(next);

    consoleWarnSpy.mockRestore();
  });

  it('applies every onAudioLevel call regardless of ordering (last-value-wins, no rejection)', () => {
    const audioHandler = vi.fn();
    registerAudioLevelHandler(audioHandler);

    window.basilAgentTaskCapture!.onAudioLevel(0.8, 10);
    window.basilAgentTaskCapture!.onAudioLevel(0.1, 3); // Out of order by audioRevision, still applied.

    expect(audioHandler).toHaveBeenNthCalledWith(1, 0.8, 10);
    expect(audioHandler).toHaveBeenNthCalledWith(2, 0.1, 3);
  });

  it('routes onThemeChanged/onFontsChanged to their registered handlers', () => {
    const themeHandler = vi.fn();
    const fontsHandler = vi.fn();
    registerThemeHandler(themeHandler);
    registerFontsHandler(fontsHandler);

    window.basilAgentTaskCapture!.onThemeChanged(sampleTheme);
    window.basilAgentTaskCapture!.onFontsChanged(sampleFonts);

    expect(themeHandler).toHaveBeenCalledWith(sampleTheme);
    expect(fontsHandler).toHaveBeenCalledWith(sampleFonts);
  });
});
