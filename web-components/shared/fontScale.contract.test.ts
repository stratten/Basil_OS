// @vitest-environment node

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const webComponentsRoot = fileURLToPath(new URL('..', import.meta.url));

// Every package scales, Settings included, so a user who needs larger text can read the window where they change it. Add a package name here only with a documented reason.
const UNSCALED_PACKAGES = new Set<string>();

const SCALE_FORM = /calc\(\s*\d*\.?\d+px\s*\*\s*var\(--text-scale,\s*1\)\s*\)/;
const DECLARATION = /(^|[;{}\s])(font-size|line-height|--font-size-[a-z0-9-]+)\s*:\s*([^;{}]*?)\s*(?:!important\s*)?(?=;|}|$)/gm;
const PIXEL_NUMBER = /(^|[^\w.-])\d*\.?\d+px\b/;

function collectCssFiles(directory: string, found: string[]): void {
  for (const entry of readdirSync(directory)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const fullPath = join(directory, entry);
    if (statSync(fullPath).isDirectory()) collectCssFiles(fullPath, found);
    else if (entry.endsWith('.css')) found.push(fullPath);
  }
}

function scaledCssFiles(): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(webComponentsRoot)) {
    if (entry === 'node_modules' || UNSCALED_PACKAGES.has(entry)) continue;
    const packageRoot = join(webComponentsRoot, entry);
    if (!statSync(packageRoot).isDirectory()) continue;
    const scanRoot = entry === 'shared' ? packageRoot : join(packageRoot, 'src');
    if (existsSync(scanRoot)) collectCssFiles(scanRoot, found);
  }
  return found.map((fullPath) => relative(webComponentsRoot, fullPath).split(sep).join('/')).sort();
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ' '));
}

/** Pixel font sizes and pixel line heights that are not inside the scale form, as `file:line property: value`. */
function unscaledDeclarations(relativePath: string): string[] {
  const source = stripComments(readFileSync(join(webComponentsRoot, relativePath), 'utf8'));
  const problems: string[] = [];
  for (const match of source.matchAll(DECLARATION)) {
    const [, , property = '', rawValue = ''] = match;
    const value = rawValue.trim();
    const withoutScaleForms = value.replace(new RegExp(SCALE_FORM.source, 'g'), '');
    if (!PIXEL_NUMBER.test(withoutScaleForms)) continue;
    const line = source.slice(0, (match.index ?? 0) + match[0].length).split('\n').length;
    problems.push(`${relativePath}:${line} ${property}: ${value}`);
  }
  return problems;
}

describe('text size scaling', () => {
  const files = scaledCssFiles();

  it('walks the shared sheets and every package, Settings included, so the scan cannot pass vacuously', () => {
    expect(files).toContain('shared/theme-layout-tokens.css');
    expect(files).toContain('AgentTaskResult/src/styles/theme.css');
    expect(files).toContain('BasilBoard/src/styles/chats.css');
    expect(files).toContain('SettingsWebComponents/src/styles/settings-elements.css');
    expect(files.length).toBeGreaterThan(100);
  });

  it('leaves no pixel font size or pixel line height outside calc(Npx * var(--text-scale, 1))', () => {
    const problems = files.flatMap(unscaledDeclarations);
    expect(problems).toEqual([]);
  });

  it('leaves no numeric inline fontSize in a scaled package component', () => {
    const problems: string[] = [];
    const collectSources = (directory: string) => {
      for (const entry of readdirSync(directory)) {
        if (entry === 'node_modules' || entry === 'dist') continue;
        const fullPath = join(directory, entry);
        if (statSync(fullPath).isDirectory()) collectSources(fullPath);
        else if (/\.tsx?$/.test(entry) && !/\.test\./.test(entry)) {
          readFileSync(fullPath, 'utf8').split('\n').forEach((text, index) => {
            if (/\bfontSize:\s*['"]?\d/.test(text)) problems.push(`${relative(webComponentsRoot, fullPath).split(sep).join('/')}:${index + 1} ${text.trim()}`);
          });
        }
      }
    };
    for (const entry of readdirSync(webComponentsRoot)) {
      if (entry === 'node_modules' || UNSCALED_PACKAGES.has(entry)) continue;
      const root = join(webComponentsRoot, entry, entry === 'shared' ? '' : 'src');
      if (existsSync(root) && statSync(root).isDirectory()) collectSources(root);
    }
    expect(problems).toEqual([]);
  });

  it('declares every shared font size token in the scale form', () => {
    const source = stripComments(readFileSync(join(webComponentsRoot, 'shared/theme-layout-tokens.css'), 'utf8'));
    const tokens = [...source.matchAll(/--(font-size-[a-z0-9-]+)\s*:\s*([^;]+);/g)];
    expect(tokens.length).toBe(14);
    for (const [, name, value] of tokens) {
      expect(value, `--${name}`).toMatch(SCALE_FORM);
    }
  });

  it('catches an unscaled declaration, so the scan itself is trustworthy', () => {
    const sample = (value: string) => [...`a { ${value}; }`.matchAll(DECLARATION)].filter(([, , , found = '']) => {
      return PIXEL_NUMBER.test(found.replace(new RegExp(SCALE_FORM.source, 'g'), ''));
    }).length;
    expect(sample('font-size: 13px')).toBe(1);
    expect(sample('line-height: 18px')).toBe(1);
    expect(sample('font-size: var(--font-size-body, 13px)')).toBe(1);
    expect(sample('--font-size-body: 14px')).toBe(1);
    expect(sample('font-size: clamp(36px, 5vw, 48px)')).toBe(1);
    expect(sample('font-size: calc(13px * var(--text-scale, 1))')).toBe(0);
    expect(sample('font-size: var(--font-size-body, calc(13px * var(--text-scale, 1)))')).toBe(0);
    expect(sample('font-size: 1.2em')).toBe(0);
    expect(sample('line-height: 1.4')).toBe(0);
    expect(sample('margin-top: 13px')).toBe(0);
  });
});
