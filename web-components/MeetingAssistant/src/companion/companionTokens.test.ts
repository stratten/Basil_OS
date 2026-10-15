import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');
const SHARED = resolve(__dirname, '../../../shared');
/** `meeting-assistant.css` imports this theme first; it defines the spacing, radius, type and font tokens. */
const AGENT_TASK_RESULT_STYLES = resolve(__dirname, '../../../AgentTaskResult/src/styles');
const companionCss = readFileSync(resolve(SRC, 'styles/companion.css'), 'utf8');

function cssFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : cssFiles(path);
    return entry.name.endsWith('.css') ? [path] : [];
  });
}

const definedTokens = new Set<string>();
for (const file of [...cssFiles(resolve(SRC, 'styles')), ...cssFiles(SHARED), resolve(AGENT_TASK_RESULT_STYLES, 'theme.css')]) {
  for (const match of readFileSync(file, 'utf8').matchAll(/(--[a-z0-9-]+)\s*:/g)) definedTokens.add(match[1]);
}
for (const match of readFileSync(resolve(SHARED, 'webTheme.ts'), 'utf8').matchAll(/'(--[a-z0-9-]+)'/g)) definedTokens.add(match[1]);

const COMPANION_SOURCES = readdirSync(__dirname)
  .filter((name) => /^Companion.*\.tsx$/.test(name) && !name.endsWith('.test.tsx'))
  .map((name) => ({ name, text: readFileSync(join(__dirname, name), 'utf8') }));

describe('the Companion styles come from the central tokens', () => {
  it('writes no color literal in companion.css', () => {
    const withoutComments = companionCss.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(withoutComments).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(withoutComments).not.toMatch(/\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\(/i);
    const colorProperty = /(?:^|[;{\s])(?:color|background|background-color|border|border-color|border-top|border-right|border-bottom|border-left|outline|outline-color|fill|stroke)\s*:\s*([^;]+);/g;
    for (const match of withoutComments.matchAll(colorProperty)) {
      const value = match[1].replace(/var\([^)]*\)/g, '').replace(/color-\w+\([^;]*\)/g, '');
      expect(value, `value "${match[1]}"`).not.toMatch(/\b(?:white|black|red|green|blue|gr[ae]y|yellow|orange|purple|pink|brown|silver|gold|navy|teal)\b/i);
    }
  });

  it('only uses tokens that are defined somewhere the Notetaker loads', () => {
    const used = new Set([...companionCss.matchAll(/var\((--[a-z0-9-]+)/g)].map((match) => match[1]));
    expect(used.size).toBeGreaterThan(10);
    for (const token of used) expect(definedTokens.has(token), `token ${token}`).toBe(true);
  });

  it('puts no inline color in the Companion components', () => {
    expect(COMPANION_SOURCES.length).toBeGreaterThan(5);
    for (const { name, text } of COMPANION_SOURCES) {
      expect(text, name).not.toMatch(/style=\{\{/);
      expect(text, name).not.toMatch(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/);
      expect(text, name).not.toMatch(/\b(?:rgb|rgba|hsl|hsla)\(/i);
    }
  });

  it('reuses the Notetaker button, switch and heading classes for the new cards', () => {
    const card = readFileSync(join(__dirname, 'CompanionProposalCard.tsx'), 'utf8');
    expect(card).toContain('meeting-record-button');
    expect(card).toContain('meeting-history-load-more-button');
    expect(readFileSync(join(__dirname, 'CompanionProposalSettings.tsx'), 'utf8')).toContain('MeetingSwitch');
  });
});
