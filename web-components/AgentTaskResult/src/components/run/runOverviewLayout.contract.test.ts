// @vitest-environment node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');

const trayCss = read('../../styles/components/detail-tray/execution-detail-tray.css');
const mapCss = read('../../styles/components/detail-tray/agent-run-map.css');
const panelCss = read('../../styles/components/detail-tray/run-overview-panel.css');
const entryCss = read('../../styles/components.css');

function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  expect(match, `${selector} rule`).not.toBeNull();
  return match![1];
}

describe('Run overview layout contract', () => {
  it('no longer assumes a fixed offset from the viewport, which cut off the last row of a long run', () => {
    expect(trayCss).not.toMatch(/calc\(100vh\s*-\s*7rem\)/);
    expect(mapCss).not.toMatch(/calc\(100vh\s*-\s*7rem\)/);
  });

  it('bounds the floating run card by the surface and lets the overview scroll inside it with room below the last row', () => {
    expect(rule(trayCss, '.execution-detail-tray--run-card')).toMatch(/max-height:\s*100%/);
    const body = rule(panelCss, '.run-overview-body');
    expect(body).toMatch(/overflow-y:\s*auto/);
    expect(body).toMatch(/min-height:\s*0/);
    expect(body).toMatch(/padding-bottom:/);
  });

  it('centers the header contents vertically with the collapse button first, and separates the divider from the body', () => {
    expect(rule(panelCss, '.detail-tray-header--overview')).toMatch(/align-items:\s*center/);
    expect(rule(panelCss, '.detail-tray-header--overview')).toMatch(/justify-content:\s*flex-start/);
    expect(rule(panelCss, '.run-overview-body')).toMatch(/padding-top:\s*var\(--padding-s\)/);
  });

  it('does not double the vertical rhythm between overview rows', () => {
    expect(rule(trayCss, '.run-card-stages')).toMatch(/gap:\s*0;/);
  });

  it('loads the panel and shared list styles from the component entry', () => {
    expect(entryCss).toContain("./components/detail-tray/run-overview-panel.css");
    expect(entryCss).toContain('shared/expandable-list.css');
  });
});
