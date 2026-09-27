import { useEffect, useState, type DragEvent } from 'react';
import type { CaptureSnapshot } from './types';
import {
  registerFontsHandler,
  registerInitHandler,
  registerSnapshotHandler,
  registerThemeHandler,
  requestSnapshot,
  sendCaptureInputReady,
  setSelectedModel,
} from './services/bridge';
import { setBaseUrl } from './services/api';
import { applyHostFonts, applyHostTheme, applyProcessingDefaults } from './app/themeBootstrap';
import CaptureHeader from './components/CaptureHeader';
import VoiceCaptureView from './components/VoiceCaptureView';
import TextCaptureView from './components/TextCaptureView';
import ReferencePathsList from './components/ReferencePathsList';

function DropZoneOverlay() {
  return (
    <div className="capture-drop-overlay" aria-hidden="true">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3v12M7 10l5 5 5-5" />
        <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
      </svg>
      <span>Drop files here</span>
    </div>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<CaptureSnapshot | null>(null);
  const [agentTaskDisplayName, setAgentTaskDisplayName] = useState('Paprika');
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  useEffect(() => {
    applyProcessingDefaults();

    const unregisterInit = registerInitHandler((payload) => {
      setBaseUrl(payload.port);
      applyHostTheme(payload.theme);
      applyHostFonts(payload.fonts);
      setAgentTaskDisplayName(payload.agentTaskDisplayName || 'Paprika');
      setSnapshot(payload.snapshot);
      setSelectedModelId(payload.snapshot.selectedModelId);
    });
    const unregisterSnapshot = registerSnapshotHandler((nextSnapshot) => {
      setSnapshot(nextSnapshot);
      setSelectedModelId(nextSnapshot.selectedModelId);
    });
    const unregisterTheme = registerThemeHandler(applyHostTheme);
    const unregisterFonts = registerFontsHandler(applyHostFonts);

    sendCaptureInputReady();

    // Recovery path for the dev-only manual-reload row (Package 4, row L2):
    // a Vite HMR reload can re-run this effect while `bridge.ts`'s module
    // state (and therefore Swift's belief that React already said ready)
    // persists across the reload, so a fresh `captureInputReady` may not
    // produce a fresh `onInit` if Swift already answered an earlier one.
    // If no snapshot has arrived shortly after, ask again explicitly.
    const recoveryTimeout = window.setTimeout(() => {
      setSnapshot((current) => {
        if (current === null) requestSnapshot();
        return current;
      });
    }, 500);

    return () => {
      window.clearTimeout(recoveryTimeout);
      unregisterInit();
      unregisterSnapshot();
      unregisterTheme();
      unregisterFonts();
    };
  }, []);

  if (!snapshot) {
    return (
      <div className="basil-webkit-window-frame">
        <div className="basil-webkit-window-surface capture-widget capture-widget--loading" />
      </div>
    );
  }

  function handleSelectedModelChange(modelId: string | null): void {
    setSelectedModelId(modelId);
    setSelectedModel(modelId);
  }

  // This widget owns `isDraggingOver` itself via plain DOM drag events,
  // mirroring `TextFollowUp.tsx`'s established (and proven working) pattern
  // for the agent task result follow-up capture area. Native (Swift) only
  // reads dropped absolute file paths off the pasteboard — see
  // `FirstClickWebView.performDragOperation` in
  // `AgentTaskResultWebViewSupportViews.swift`, inherited unchanged by
  // `DropTargetWebView` in `AgentTaskCaptureInputWebView.swift` — and always
  // falls through to `super.performDragOperation`, so WebKit still dispatches
  // a real `drop` DOM event here. Calling `preventDefault()` on that event
  // (and on `dragover`, per the HTML5 drag-and-drop spec) is what stops
  // WebKit's default behavior of navigating this webview to the dropped file.
  function handleDragOver(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingOver(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setIsDraggingOver(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingOver(false);
  }

  return (
    <div className="basil-webkit-window-frame">
      <div
        className="basil-webkit-window-surface capture-widget"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <CaptureHeader snapshot={snapshot} displayName={agentTaskDisplayName} />
        {snapshot.inputModality === 'voice' ? (
          <VoiceCaptureView
            snapshot={snapshot}
            selectedModelId={selectedModelId}
            onModelChange={handleSelectedModelChange}
          />
        ) : (
          <TextCaptureView
            snapshot={snapshot}
            selectedModelId={selectedModelId}
            onModelChange={handleSelectedModelChange}
          />
        )}
        {snapshot.referencePaths.length > 0 ? (
          <ReferencePathsList paths={snapshot.referencePaths} />
        ) : null}
        {isDraggingOver ? <DropZoneOverlay /> : null}
      </div>
    </div>
  );
}
