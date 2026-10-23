import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');
const SHARED = resolve(__dirname, '../../../shared');
const AGENT_TASK_RESULT_STYLES = resolve(__dirname, '../../../AgentTaskResult/src/styles');
const css = readFileSync(resolve(SRC, 'styles/cloud-transcription.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

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

describe('the cloud transcription styles come from the central tokens', () => {
  it('writes no color literal', () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\(/i);
    expect(css).not.toMatch(/color-\w+\(/);
    const colorProperty = /(?:^|[;{\s])(?:color|background|background-color|border|border-color|border-left|outline|fill|stroke)\s*:\s*([^;]+);/g;
    for (const match of css.matchAll(colorProperty)) {
      const value = match[1].replace(/var\([^)]*\)/g, '');
      expect(value, `value "${match[1]}"`).not.toMatch(/\b(?:white|black|red|green|blue|gr[ae]y|yellow|orange|purple|pink|brown|silver|gold|navy|teal)\b/i);
    }
  });

  it('only uses variables that a central stylesheet defines', () => {
    const used = new Set([...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((match) => match[1]));
    expect(used.size).toBeGreaterThan(5);
    for (const token of used) expect(definedTokens.has(token), `${token} is not defined centrally`).toBe(true);
  });

  it('is loaded by the Notetaker entry', () => {
    expect(readFileSync(resolve(SRC, 'entries/meeting-assistant.tsx'), 'utf8')).toContain("import '../styles/cloud-transcription.css';");
  });
});
