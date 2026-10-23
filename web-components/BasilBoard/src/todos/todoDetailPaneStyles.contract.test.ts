import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('To-Do detail pane and workspace styles', () => {
  const css = readFileSync('src/styles/todos.css', 'utf8');

  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
    expect(match, `missing rule for ${selector}`).not.toBeNull();
    return match![1];
  }

  it('does not restyle markdown lists inside the Agent Task result through the work-history list rule', () => {
    expect(css).not.toMatch(/\.todo-detail-work-history\s+ul/);
    expect(css).toContain('.todo-detail-work-history > p');
  });

  it('keeps the Agent Task card on theme tokens with no hard-coded brown overrides', () => {
    for (const brown of ['#4a3200', '#6b4f0f', '#8a5c00', '#5c3d00', '#fffdf8', '#fff1d9', '#fff4d8', '#c48d12', '#c46a16']) {
      expect(css.toLowerCase()).not.toContain(brown);
    }
    expect(rule('.todo-worker-status-card')).toContain('var(--background-primary)');
    expect(rule('.todo-worker-status-card')).not.toContain('linear-gradient');
    expect(css).toContain('color-mix(in srgb, var(--warning-base) 12%, var(--background-primary))');
  });

  it('outranks the pane section-heading style for headings rendered inside the result card', () => {
    for (const level of [1, 2, 3, 4, 5, 6]) {
      expect(css).toContain(`.todo-worker-status-card .home-markdown h${level}`);
    }
    expect(rule('.todo-worker-status-card .home-markdown h1,\n.todo-worker-status-card .home-markdown h2,\n.todo-worker-status-card .home-markdown h3,\n.todo-worker-status-card .home-markdown h4,\n.todo-worker-status-card .home-markdown h5,\n.todo-worker-status-card .home-markdown h6')).toContain('color: inherit');
  });

  it('spaces the workspace header actions and tightens the empty state', () => {
    const actions = rule('.todo-workspace-header-actions');
    expect(actions).toContain('display: flex');
    expect(actions).toContain('flex-wrap: wrap');
    expect(actions).toMatch(/gap:\s*8px/);
    const empty = rule('.todo-workspace-header p,\n.todo-workspace-empty');
    expect(empty).toContain('margin: 0');
    expect(empty).toContain('line-height: 1.4');
    expect(rule('.todo-workspace-transcript')).toContain('min-height: 0');
  });

  it('keeps a faint visible outline on the description and notes editors at rest, stronger on hover', () => {
    const resting = rule('.todo-detail-rich-text-composer');
    expect(resting).toMatch(/border:\s*1px solid color-mix\(in srgb, var\(--primary\) 18%, transparent\)/);
    expect(resting).not.toContain('solid transparent');
    expect(rule('.todo-detail-rich-text-composer:hover')).toContain('var(--primary) 38%');
  });

  it('keeps plain-text line breaks visible in the detail-pane editors and reveals the toolbar only on focus', () => {
    expect(css).toContain('.todo-detail-rich-text-composer .rich-text-composer-editor {\n  white-space: pre-wrap;');
    expect(rule('.todo-detail-rich-text-composer .rich-text-composer-toolbar')).toContain('display: none');
    expect(rule('.todo-detail-rich-text-composer:focus-within .rich-text-composer-toolbar')).toContain('display: flex');
  });

  it('no longer ships the Edit toggle styling', () => {
    expect(css).not.toContain('todo-detail-edit-toggle');
    expect(css).not.toContain('todo-detail-edit-form');
  });
});
