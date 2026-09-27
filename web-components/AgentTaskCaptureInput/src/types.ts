export type InputModality = 'voice' | 'text';

// The oracle's `ReferencePathItem` (dossier §1.2 item 3) shows a
// folder-vs-document glyph based on a filesystem check the browser layer
// cannot perform itself; Swift computes and forwards it once per snapshot
// instead (see `05_Bridge_Contract_And_Types.md` section 5.7).
export interface ReferencePathEntry {
  path: string;
  isDirectory: boolean;
}

export interface CaptureSnapshot {
  revision: number;
  inputModality: InputModality;
  isCapturing: boolean;
  hasCompleted: boolean;
  statusMessage: string;
  wordsDetected: string[];
  silenceDetectionActive: boolean;
  silenceRemaining: number;
  useIntelligentCapture: boolean;
  progressPercentage: number;
  remainingSeconds: number;
  agentTaskHotkeyDisplay: string | null;
  textPrompt: string;
  isSubmittingTextPrompt: boolean;
  selectedModelId: string | null;
  referencePaths: ReferencePathEntry[];
  isDraggingOver: boolean;
}

// This package's own local copy, matching `AgentTaskResult/src/types.ts`'s
// `ThemeConfig`/`FontConfig` shape field-for-field. Every existing WKWebView
// package in this repository defines its own local copy rather than sharing
// one across packages — see `05_Bridge_Contract_And_Types.md` section 5.9 for
// the confirmed repository-wide precedent. `readyBase`/`readyAccent` are
// deliberately NOT included here (same reasoning as `AgentTaskResult`): they
// are fixed, non-user-configurable defaults declared directly in
// `styles/theme.css`, never bridged from Swift.
import type { FontConfig as SharedFontConfig, ThemeConfig as SharedThemeConfig } from '@shared/webTheme';
export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  secondary: string;
  textPrimary: string;
};
export type FontConfig = SharedFontConfig & {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
};

export interface CaptureInitMessage {
  port: number;
  agentTaskDisplayName: string;
  theme: ThemeConfig;
  fonts: FontConfig;
  snapshot: CaptureSnapshot;
}

export interface CaptureModelPickerOption {
  id: string;
  displayName: string;
  category: 'local' | 'api' | 'custom';
}

export interface CaptureModelPickerAnchorRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

// Swift -> JS
export type CaptureNativeMessage =
  | { type: 'init'; payload: CaptureInitMessage }
  | { type: 'onSnapshot'; snapshot: CaptureSnapshot }
  | { type: 'onAudioLevel'; level: number; audioRevision: number }
  | { type: 'onThemeChanged'; theme: ThemeConfig }
  | { type: 'onFontsChanged'; fonts: FontConfig };

// JS -> Swift
export type CaptureInputMessage =
  | { type: 'captureInputReady' }
  | { type: 'requestSnapshot' }
  | { type: 'requestCaptureResize'; width: number; height: number }
  | { type: 'captureHeaderExtent'; height: number }
  | { type: 'enterVoiceMode' }
  | { type: 'enterTextEntryMode' }
  | { type: 'updateTextDraft'; text: string }
  | { type: 'submitTextPrompt'; text: string; modelId?: string }
  | { type: 'setSelectedModel'; modelId: string | null }
  | { type: 'showNativeModelPicker'; models: CaptureModelPickerOption[]; selectedModelId: string | null; anchorRect: CaptureModelPickerAnchorRect }
  | { type: 'cancelCapture' }
  | { type: 'pickReferenceFiles' }
  | { type: 'removeReferencePath'; index: number }
  | { type: 'openReferencePath'; path: string }
  | { type: 'filesDropped'; paths: string[] }
  | { type: 'setDraggingOver'; isDraggingOver: boolean }
  | { type: 'showHistory' };

// Faithful TypeScript port of the Swift oracle's `isProcessingState`
// computed property (`AgentTaskCaptureWidget.swift`, quoted in
// `01_Canonical_Source_Dossier.md` section 1.6). Kept as a standalone
// exported function (not inlined into the two derivations below) because
// both `deriveBubbleMode` and `deriveBubbleColors` need the identical
// predicate and the oracle itself factors it out as its own computed
// property for the same reason (`currentBubbleMode` and `bubbleColors` both
// reference `isProcessingState`).
export function isCaptureProcessingState(statusMessage: string, isCapturing: boolean): boolean {
  return (
    statusMessage.includes('Processing') ||
    statusMessage.includes('Finishing up') ||
    (!isCapturing && (statusMessage.includes('Processing') || statusMessage === 'Canceled'))
  );
}

// Faithful port of the oracle's `currentBubbleMode` computed property.
// Return type intentionally matches `shared/bubble/AnimatedBubble.tsx`'s
// exported `BubbleMode` union so callers can pass this straight into the
// shared `<AnimatedBubble mode={...} />` prop without a cast.
export function deriveBubbleMode(snapshot: CaptureSnapshot): 'ambient' | 'audioResponsive' | 'processing' {
  if (snapshot.isCapturing) return 'audioResponsive';
  if (isCaptureProcessingState(snapshot.statusMessage, snapshot.isCapturing)) return 'processing';
  return 'ambient';
}

// Faithful port of the oracle's `bubbleColors` computed property. Returns
// CSS `var(...)` references (not resolved hex strings) so the shared
// `AnimatedBubble` component's own `getComputedStyle`-based color resolution
// (see `shared/bubble/AnimatedBubble.tsx`'s `resolve` helper) continues to
// react correctly to live `--recording-base`/`--processing-base`/
// `--ready-base` custom-property changes pushed by `onThemeChanged`, exactly
// as it already does for every other consumer of that component.
export function deriveBubbleColors(snapshot: CaptureSnapshot): { baseColor: string; accentColor: string } {
  if (snapshot.isCapturing) {
    return { baseColor: 'var(--recording-base)', accentColor: 'var(--recording-accent)' };
  }
  if (isCaptureProcessingState(snapshot.statusMessage, snapshot.isCapturing)) {
    return { baseColor: 'var(--processing-base)', accentColor: 'var(--processing-accent)' };
  }
  return { baseColor: 'var(--ready-base)', accentColor: 'var(--ready-accent)' };
}
