import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/** Every web view that renders Markdown, plus the setup assistant's hand-built model comparison table that must look the same: the component that emits the container class, the container class, and the stylesheet or entry file that must import shared/text/markdown-table.css. Adding a Markdown surface is one line here and one class in shared/text/markdown-table.css. */
const MARKDOWN_SURFACES = [
  { renderer: 'AgentTaskResult/src/components/MarkdownRenderer.tsx', container: 'result-section', importer: 'AgentTaskResult/src/styles/components/result-content.css', importLine: "@import '../../../../shared/text/markdown-table.css';" },
  { renderer: 'BasilBoard/src/home/HomeMarkdown.tsx', container: 'home-markdown', importer: 'BasilBoard/src/styles/home-markdown-blocks.css', importLine: "@import '../../../shared/text/markdown-table.css';" },
  { renderer: 'MeetingAssistant/src/lib/markdown.tsx', container: 'meeting-markdown', importer: 'MeetingAssistant/src/styles/meeting-assistant.css', importLine: "@import '../../../shared/text/markdown-table.css';" },
  { renderer: 'SettingsWebComponents/src/components/context/WritingSampleMarkdown.tsx', container: 'writing-examples-markdown', importer: 'SettingsWebComponents/src/main.tsx', importLine: "import '@shared/text/markdown-table.css'" },
  { renderer: 'AssistantSession/src/components/history/HistoryDetail.tsx', container: 'assistant-output-history-detail__output', importer: 'AssistantSession/src/styles/assistant-session.css', importLine: "@import '../../../shared/text/markdown-table.css';" },
  { renderer: 'SetupAssistantWebComponents/src/components/intro/ModelComparison.tsx', container: 'model-comparison', importer: 'SetupAssistantWebComponents/src/styles/setup-assistant.model-comparison.css', importLine: "@import '../../../shared/text/markdown-table.css';" },
] as const;

function read(path: string): string {
  return readFileSync(`../${path}`, 'utf8');
}

const sharedCss = read('shared/text/markdown-table.css');
const containerLists = [...sharedCss.matchAll(/^:where\(([^)]+)\)/gm)].map(match => match[1].split(',').map(name => name.trim()));

describe('shared Markdown table style', () => {
  it('rounds the table and every outer cell the same way on every surface', () => {
    expect(sharedCss).toContain('border-collapse: separate;');
    expect(sharedCss).toMatch(/border-radius: var\(--corner-radius-small, 6px\);/);
    for (const corner of ['top-left', 'top-right', 'bottom-left', 'bottom-right']) {
      expect(sharedCss).toContain(`border-${corner}-radius`);
    }
  });

  it('keeps a narrow numeric column wide enough for two digits', () => {
    expect(sharedCss).toMatch(/min-width: 3ch;/);
  });

  it('sets word-break on the cells themselves so a container around the table cannot squeeze a column to one character', () => {
    const cellRule = sharedCss.match(/:is\(th, td\) \{[^}]*\}/)?.[0] ?? '';
    expect(cellRule).toContain('word-break: normal;');
  });

  it('repeats the same container list in every rule', () => {
    expect(containerLists.length).toBeGreaterThan(5);
    for (const list of containerLists) {
      expect(list).toEqual(containerLists[0]);
    }
  });

  it.each(MARKDOWN_SURFACES)('covers $container', ({ renderer, container, importer, importLine }) => {
    expect(containerLists[0]).toContain(`.${container}`);
    const rendererSource = read(renderer);
    expect(rendererSource).toContain(container);
    expect(read(importer)).toContain(importLine);
  });

  it('lists no container that is not a known Markdown surface', () => {
    const known = MARKDOWN_SURFACES.map(surface => `.${surface.container}`).sort();
    expect([...containerLists[0]].sort()).toEqual(known);
  });
});

describe('surface table overrides', () => {
  it('does not let the review workspace force equal column widths', () => {
    const css = read('AgentTaskResult/src/styles/components/artifact-review-workspace.css');
    expect(css).not.toMatch(/table-layout:\s*fixed/);
  });

  it('does not square off a table in any surface stylesheet', () => {
    for (const path of [
      'AgentTaskResult/src/styles/components/result-content.css',
      'BasilBoard/src/styles/home-markdown-blocks.css',
    ]) {
      expect(read(path)).not.toMatch(/border-collapse:\s*collapse/);
    }
  });
});
