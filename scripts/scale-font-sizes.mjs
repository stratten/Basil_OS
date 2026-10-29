#!/usr/bin/env node
// Wraps every hard-coded pixel font size and pixel line height in the web components' stylesheets in `calc(Npx * var(--text-scale, 1))`, so the app-wide text size setting reaches them.
//
// What it rewrites, in every package's stylesheets, Settings included:
//   font-size: 13px                          -> font-size: calc(13px * var(--text-scale, 1))
//   line-height: 18px                        -> line-height: calc(18px * var(--text-scale, 1))
//   font-size: var(--font-size-body, 13px)   -> font-size: var(--font-size-body, calc(13px * var(--text-scale, 1)))
//   --font-size-callout: 13px                -> --font-size-callout: calc(13px * var(--text-scale, 1))
// What it leaves alone: unitless and relative values (1.4, 1em, inherit), values already scaled, and anything inside a comment. Values it cannot rewrite mechanically (for example `clamp(...)`) are reported by the contract test `web-components/shared/fontScale.contract.test.ts` and edited by hand.
//
// Usage:
//   node scripts/scale-font-sizes.mjs          rewrite the files in place and print what changed
//   node scripts/scale-font-sizes.mjs --check  change nothing; exit 1 when any file would change

import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const webComponentsRoot = join(repositoryRoot, 'web-components');
const EXCLUDED_PACKAGES = new Set(['node_modules']);
const SCALE = 'var(--text-scale, 1)';

const NUMBER = String.raw`\d*\.?\d+`;
const PIXEL_VALUE = new RegExp(`^(${NUMBER})px$`);
const PIXEL_FALLBACK = new RegExp(String.raw`(var\(\s*--[a-z0-9-]+\s*,\s*)(${NUMBER})px(\s*\))`, 'g');
const SCALED_DECLARATION = new RegExp(
  String.raw`(^|[;{}\s])(font-size|line-height|--font-size-[a-z0-9-]+)(\s*:\s*)([^;{}]*?)(\s*!important)?(\s*)(?=;|}|$)`,
  'gm',
);

function scaled(pixels) {
  return `calc(${pixels}px * ${SCALE})`;
}

/** The scaled form of one declaration value, or the value unchanged when there is nothing to scale. */
export function scaleValue(value) {
  if (value.includes('--text-scale')) return value;
  const direct = PIXEL_VALUE.exec(value.trim());
  if (direct) return scaled(direct[1]);
  return value.replace(PIXEL_FALLBACK, (_match, open, pixels, close) => `${open}${scaled(pixels)}${close}`);
}

/** Rewrites the declarations of one stylesheet, leaving comments untouched. Returns the new source and how many declarations changed. */
export function scaleCssSource(source) {
  let changes = 0;
  const segments = source.split(/(\/\*[\s\S]*?\*\/)/g);
  const output = segments.map((segment, index) => {
    if (index % 2 === 1) return segment;
    return segment.replace(SCALED_DECLARATION, (match, lead, property, colon, value, important = '', trailing) => {
      const next = scaleValue(value);
      if (next === value) return match;
      changes += 1;
      return `${lead}${property}${colon}${next}${important}${trailing}`;
    });
  });
  return { output: output.join(''), changes };
}

function collectCssFiles(directory, found) {
  for (const entry of readdirSync(directory)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const fullPath = join(directory, entry);
    if (statSync(fullPath).isDirectory()) collectCssFiles(fullPath, found);
    else if (entry.endsWith('.css')) found.push(fullPath);
  }
}

/** Every stylesheet the text size setting applies to: each package's `src` plus `shared`. */
export function scaledStylesheets() {
  const found = [];
  for (const entry of readdirSync(webComponentsRoot)) {
    if (EXCLUDED_PACKAGES.has(entry)) continue;
    const packageRoot = join(webComponentsRoot, entry);
    if (!statSync(packageRoot).isDirectory()) continue;
    const scanRoot = entry === 'shared' ? packageRoot : join(packageRoot, 'src');
    try {
      collectCssFiles(scanRoot, found);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  return found.sort();
}

function main() {
  const checkOnly = process.argv.includes('--check');
  let filesChanged = 0;
  let declarationsChanged = 0;
  for (const file of scaledStylesheets()) {
    const source = readFileSync(file, 'utf8');
    const { output, changes } = scaleCssSource(source);
    if (changes === 0) continue;
    filesChanged += 1;
    declarationsChanged += changes;
    console.log(`${checkOnly ? 'would change' : 'changed'} ${relative(repositoryRoot, file)}: ${changes}`);
    if (!checkOnly) writeFileSync(file, output);
  }
  console.log(`${declarationsChanged} declaration(s) in ${filesChanged} file(s) ${checkOnly ? 'need scaling' : 'scaled'}.`);
  if (checkOnly && declarationsChanged > 0) process.exit(1);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
