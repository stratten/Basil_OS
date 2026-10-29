import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/** Every window entry point that plays the blueprint reveal, relative to web-components. Adding a surface to the reveal is one line in its entry file and one line here. */
const REVEAL_ENTRIES = [
  // Pop-ups.
  'AssistantSession/src/entries/assistant-session.tsx',
  'AssistantSession/src/entries/assistant-output-history.tsx',
  'AgentTaskCaptureInput/src/main.tsx',
  'AgentTaskResult/src/main.tsx',
  'TranscriptionWidget/src/entries/transcription-widget.tsx',
  'TranscriptionWidget/src/entries/audio-file-upload.tsx',
  'MeetingAssistant/src/entries/meeting-companion.tsx',
  'MeetingDetectedMiniPanel/src/main.tsx',
  'ScheduledRunMiniPanel/src/main.tsx',
  'ModelDownloadMiniPanel/src/entries/model-download-mini-panel.tsx',
  'SetupAssistantResumeToast/src/entries/setup-assistant-resume-toast.tsx',
  'StartupLoadingWindow/src/entries/startup-loading.tsx',
  'AmbientSuggestionsPanel/src/main.tsx',
  // Workspace windows.
  'BasilBoard/src/main.tsx',
  'BasilBoard/src/standalone/conversation-main.tsx',
  'MeetingAssistant/src/entries/meeting-assistant.tsx',
  'MeetingAssistant/src/entries/meeting-analysis.tsx',
  'ProfileMemorySkillsEditor/src/entries/profile-editor.tsx',
  'SkillReconciliationWorkspace/src/main.tsx',
  'AgentTaskResult/src/entries/file-preview.tsx',
  'AgentTaskResult/src/entries/local-web-preview.tsx',
  'PowerUserGuidePanel/src/entries/power-user-guide-panel.tsx',
  // First-run and preferences windows.
  'SetupAssistantWebComponents/src/entries/setup-assistant.tsx',
  'SetupAssistantWebComponents/src/entries/setup-permissions.tsx',
  'SettingsWebComponents/src/main.tsx',
];

function read(path: string): string {
  return readFileSync(`../${path}`, 'utf8');
}

describe('blueprint reveal entry points', () => {
  it.each(REVEAL_ENTRIES)('%s installs the reveal from the shared controller', (entry) => {
    const source = read(entry);
    expect(source).toMatch(/^import \{ installBlueprintReveal \} from '@shared\/blueprintController';?$/m);
    expect(source).toMatch(/^installBlueprintReveal\(/m);
  });
});

describe('blueprint reveal contract', () => {
  const css = read('shared/blueprint-reveal.css');
  const controller = read('shared/blueprintController.ts');

  it('keys every hiding rule off the frame attribute the controller sets', () => {
    expect(controller).toContain("export const BLUEPRINT_FRAME_ATTRIBUTE = 'data-basil-blueprint';");
    expect(css).toContain('.basil-webkit-window-frame[data-basil-blueprint="hidden"] .basil-webkit-window-surface {\n  opacity: 0;\n  pointer-events: none;');
    expect(css).toContain('.basil-webkit-window-frame[data-basil-blueprint="hidden"]::before,\n.basil-webkit-window-frame[data-basil-blueprint="hidden"]::after {\n  opacity: 0;');
  });

  it('holds back and fades in the metallic sheen layer together with the rest of the window chrome', () => {
    expect(css).toContain('html[data-surface-finish] .basil-webkit-window-frame[data-basil-blueprint="hidden"] > .basil-surface-finish-overlay {\n  opacity: 0;');
    expect(css).toContain('html[data-surface-finish] .basil-webkit-window-frame[data-basil-blueprint="reveal"] > .basil-surface-finish-overlay {\n  animation: basil-blueprint-sheen-in');
    expect(read('shared/surfaceFinish.ts')).toContain("const SURFACE_OVERLAY_CLASS = 'basil-surface-finish-overlay';");
  });

  it('skips embedded panes, which have no window chrome of their own', () => {
    expect(controller).toContain("const EMBEDDED_FRAME_CLASS = 'basil-webkit-window-frame--embedded';");
  });

  it('is signaled by the shared host theme bootstrap', () => {
    expect(read('shared/webTheme.ts')).toContain('markHostThemeApplied();');
  });
});
