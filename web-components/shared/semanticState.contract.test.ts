// @vitest-environment node

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const webComponentsRoot = fileURLToPath(new URL('..', import.meta.url));
const sharedFile = 'shared/semantic-state.css';
const expectedTokens = ['notice-base', 'notice-text', 'warning-text', 'error-text'];
const roleReference = /--notice-base|--notice-text|--warning-text|--error-text|outcome-partial-mark/;

/** Each consuming package and the file that brings the shared sheet into its bundle. */
const sheetProviders: Record<string, { file: string; mustContain: string }> = {
  AgentTaskResult: { file: 'AgentTaskResult/src/styles/theme.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  SettingsWebComponents: { file: 'SettingsWebComponents/src/styles/appearance-settings.css', mustContain: "@import '../../../AgentTaskResult/src/styles/theme.css';" },
  MeetingAssistant: { file: 'MeetingAssistant/src/styles/meeting-assistant.css', mustContain: "@import '../../../AgentTaskResult/src/styles/theme.css';" },
  SetupAssistantWebComponents: { file: 'SetupAssistantWebComponents/src/styles/setup-assistant.shared.css', mustContain: "@import '../../../AgentTaskResult/src/styles/theme.css';" },
  BasilBoard: { file: 'BasilBoard/src/main.tsx', mustContain: "import '@agent-task/styles/theme.css';" },
  TranscriptionWidget: { file: 'TranscriptionWidget/src/styles/transcription-widget.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  ModelDownloadMiniPanel: { file: 'ModelDownloadMiniPanel/src/styles/panel.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  AssistantSession: { file: 'AssistantSession/src/styles/assistant-session.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  AgentTaskCaptureInput: { file: 'AgentTaskCaptureInput/src/styles/capture-widget.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  ProfileMemorySkillsEditor: { file: 'ProfileMemorySkillsEditor/src/styles/profile-editor.css', mustContain: "@import '../../../shared/semantic-state.css';" },
  SkillReconciliationWorkspace: { file: 'SkillReconciliationWorkspace/src/styles/theme.css', mustContain: "@import '../../../shared/semantic-state.css';" },
};

/** A second bundle entry inside a package listed above that needs its own import. */
const extraProviders = [{ file: 'AssistantSession/src/styles/assistant-output-history.css', mustContain: "@import '../../../shared/semantic-state.css';" }];

function collectCssFiles(directory: string, found: string[]): void {
  for (const entry of readdirSync(directory)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const fullPath = join(directory, entry);
    if (statSync(fullPath).isDirectory()) collectCssFiles(fullPath, found);
    else if (entry.endsWith('.css')) found.push(fullPath);
  }
}

function allCssFiles(): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(webComponentsRoot)) {
    if (entry === 'node_modules') continue;
    const packageRoot = join(webComponentsRoot, entry);
    if (!statSync(packageRoot).isDirectory()) continue;
    const scanRoot = entry === 'shared' ? packageRoot : join(packageRoot, 'src');
    if (existsSync(scanRoot)) collectCssFiles(scanRoot, found);
  }
  return found.map((fullPath) => relative(webComponentsRoot, fullPath).split(sep).join('/')).sort();
}

function readSource(relativePath: string): string {
  return readFileSync(join(webComponentsRoot, relativePath), 'utf8');
}

describe('shared semantic-state sheet', () => {
  it('declares exactly the four role tokens and the partial-outcome mark', () => {
    const source = readSource(sharedFile).replace(/\/\*[\s\S]*?\*\//g, '');
    const declared = [...source.matchAll(/--([a-z0-9-]+)\s*:/g)].map((match) => match[1]);
    expect(declared).toEqual(expectedTokens);
    expect(source).toContain('.outcome-partial-mark');
  });

  it('is found by the CSS walk, so the scans below cannot pass vacuously', () => {
    expect(allCssFiles()).toContain(sharedFile);
  });

  it('is brought into every consuming package bundle', () => {
    for (const [name, provider] of Object.entries(sheetProviders)) {
      expect(readSource(provider.file), `${name}: ${provider.file}`).toContain(provider.mustContain);
    }
    for (const provider of extraProviders) {
      expect(readSource(provider.file), provider.file).toContain(provider.mustContain);
    }
  });

  it('is only referenced by packages that receive the sheet (shared sheets must use a var() fallback)', () => {
    const offenders: string[] = [];
    let referencing = 0;
    for (const file of allCssFiles()) {
      if (file === sharedFile) continue;
      const source = readSource(file);
      if (!roleReference.test(source)) continue;
      referencing += 1;
      const packageName = file.split('/')[0] ?? '';
      if (packageName === 'shared') {
        const references = [...source.matchAll(/var\(--(?:notice-base|notice-text|warning-text|error-text)(,[^)]*)?\)/g)];
        if (references.some((reference) => reference[1] === undefined)) offenders.push(`${file}: shared CSS needs a var() fallback`);
      } else if (!(packageName in sheetProviders)) {
        offenders.push(`${file}: package does not receive ${sharedFile}`);
      }
    }
    expect(offenders).toEqual([]);
    expect(referencing).toBeGreaterThanOrEqual(0);
  });

  it('is not redefined by any package theme', () => {
    const redefinitions: string[] = [];
    for (const file of allCssFiles()) {
      if (file === sharedFile) continue;
      const source = readSource(file).replace(/\/\*[\s\S]*?\*\//g, '');
      for (const token of expectedTokens) {
        if (new RegExp(`^\\s*--${token}\\s*:`, 'm').test(source)) redefinitions.push(`${file} --${token}`);
      }
    }
    expect(redefinitions).toEqual([]);
  });
});
