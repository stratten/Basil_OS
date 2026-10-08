// @vitest-environment node

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const webComponentsRoot = fileURLToPath(new URL('..', import.meta.url));
const sharedLayoutFile = 'shared/theme-layout-tokens.css';

const fullSetImporters = [
  'AgentTaskResult/src/styles/theme.css',
  'SkillReconciliationWorkspace/src/styles/theme.css',
];

const documentedOverrides: Record<string, Record<string, string>> = {
  'ProfileMemorySkillsEditor/src/styles/profile-editor.css': {
    'corner-radius-small': '8px',
    'corner-radius-large': '18px',
    'font-size-status-small': '12px',
  },
};

const expectedTokens = [
  'corner-radius-small',
  'corner-radius-medium',
  'corner-radius-large',
  'padding-xs',
  'padding-s',
  'padding-m',
  'padding-l',
  'padding-xl',
  'border-thin',
  'border-medium',
  'shadow-light',
  'shadow-medium',
  'shadow-dark',
  'font-size-large-title',
  'font-size-title1',
  'font-size-title2',
  'font-size-title3',
  'font-size-headline',
  'font-size-subheadline',
  'font-size-body',
  'font-size-callout',
  'font-size-footnote',
  'font-size-caption',
  'font-size-code',
  'font-size-code-small',
  'font-size-status-small',
  'font-size-status-tiny',
  'sidebar-collapsed-width',
  'sidebar-expanded-width',
];

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

function rootDeclarations(relativePath: string): Map<string, string> {
  const source = readSource(relativePath).replace(/\/\*[\s\S]*?\*\//g, '');
  const declarations = new Map<string, string>();
  for (const block of source.matchAll(/:root\s*\{([^}]*)\}/g)) {
    for (const declaration of (block[1] ?? '').matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)) {
      const [, name, value] = declaration;
      if (name !== undefined && value !== undefined) declarations.set(name, value.split(/\s+/).filter(Boolean).join(' '));
    }
  }
  return declarations;
}

describe('shared layout tokens', () => {
  const canonical = rootDeclarations(sharedLayoutFile);

  it('declares exactly the expected layout tokens', () => {
    expect([...canonical.keys()]).toEqual(expectedTokens);
  });

  it('is found by the CSS walk, so the drift scan cannot pass vacuously', () => {
    const files = allCssFiles();
    expect(files).toContain(sharedLayoutFile);
    expect(files).toContain('AgentTaskCaptureInput/src/styles/theme.css');
    expect(files).toContain('TranscriptionWidget/src/styles/audio-file-upload.css');
  });

  it('matches every package :root declaration of a layout token, except documented overrides', () => {
    const mismatches: string[] = [];
    let compared = 0;
    for (const file of allCssFiles()) {
      if (file === sharedLayoutFile) continue;
      const declarations = rootDeclarations(file);
      for (const token of expectedTokens) {
        const actual = declarations.get(token);
        if (actual === undefined) continue;
        compared += 1;
        const expected = documentedOverrides[file]?.[token] ?? canonical.get(token);
        if (actual !== expected) mismatches.push(`${file} --${token}: ${actual} (expected ${expected})`);
      }
    }
    expect(mismatches).toEqual([]);
    expect(compared).toBeGreaterThan(20);
  });

  it('keeps each documented override declared and different from the shared value', () => {
    for (const [file, overrides] of Object.entries(documentedOverrides)) {
      const declarations = rootDeclarations(file);
      for (const [token, value] of Object.entries(overrides)) {
        expect(declarations.get(token), `${file} --${token}`).toBe(value);
        expect(value, `${file} --${token} no longer differs from the shared value`).not.toBe(canonical.get(token));
      }
    }
  });

  it('has the full-set theme files import the shared sheet and declare no layout token locally', () => {
    for (const file of fullSetImporters) {
      expect(readSource(file), file).toContain("@import '../../../shared/theme-layout-tokens.css';");
      const declarations = rootDeclarations(file);
      expect(expectedTokens.filter((token) => declarations.has(token)), file).toEqual([]);
    }
  });
});
