// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApproveCircleIcon } from '@shared/CircleControlIcons';
import { DecisionActions, DecisionButton } from './DecisionButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function only(): HTMLButtonElement {
  const button = container.querySelector('button');
  if (!button) throw new Error('Expected a button.');
  return button;
}

describe('DecisionButton', () => {
  it('draws only the icon, and keeps the word as the accessible name', () => {
    act(() => root.render(<DecisionButton tone="approve" icon={<ApproveCircleIcon />} label="Approve" onClick={vi.fn()} />));

    expect(only().querySelector('.decision-btn__icon svg')).not.toBeNull();
    expect(only().querySelector('.decision-btn__icon')?.getAttribute('aria-hidden')).toBe('true');
    expect(only().querySelector('.decision-btn__label')?.textContent).toBe('Approve');
    expect(only().textContent).toBe('Approve');
    expect(only().className).toBe('decision-btn decision-btn--approve');
  });

  it('shows the label alone as the tooltip, or the label then what the action does', () => {
    act(() => root.render(<DecisionButton tone="neutral" icon={<ApproveCircleIcon />} label="Skip" onClick={vi.fn()} />));
    expect(only().getAttribute('title')).toBe('Skip');

    act(() => root.render(
      <DecisionButton tone="neutral" icon={<ApproveCircleIcon />} label="Skip" title="set this question aside" onClick={vi.fn()} />,
    ));
    expect(only().getAttribute('title')).toBe('Skip: set this question aside');
  });

  it('reports a click, ignores one while disabled, and exposes a pressed toggle', () => {
    const onClick = vi.fn();
    act(() => root.render(<DecisionButton tone="primary" icon={<ApproveCircleIcon />} label="Continue" onClick={onClick} pressed />));
    expect(only().getAttribute('aria-pressed')).toBe('true');
    act(() => only().click());
    expect(onClick).toHaveBeenCalledTimes(1);

    act(() => root.render(<DecisionButton tone="primary" icon={<ApproveCircleIcon />} label="Continue" onClick={onClick} disabled />));
    act(() => only().click());
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('marks a lead button, and wraps buttons in the shared row', () => {
    act(() => root.render(
      <DecisionActions className="extra">
        <DecisionButton tone="stop" icon={<ApproveCircleIcon />} label="Stop task" lead onClick={vi.fn()} />
        <DecisionButton tone="approve" icon={<ApproveCircleIcon />} label="Approve" onClick={vi.fn()} />
      </DecisionActions>,
    ));

    expect(container.querySelector('.decision-actions.extra')).not.toBeNull();
    const buttons = Array.from(container.querySelectorAll('button'));
    expect(buttons[0].className).toContain('decision-btn--lead');
    expect(buttons[1].className).not.toContain('decision-btn--lead');
  });
});

describe('decision button stylesheet', () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(resolve(here, '../../styles/components/decision-buttons.css'), 'utf8');

  it('sizes every button as a 28px icon button like the Send button, with no width growth', () => {
    const rule = css.match(/\.decision-btn \{[^}]*\}/)?.[0] ?? '';
    expect(rule).toContain('width: 28px');
    expect(rule).toContain('min-height: 28px');
    expect(rule).toContain('flex: 0 0 auto');
  });

  it('draws icons at 17px on outlined and tinted buttons and 16px on the solid Continue button, so the rings look the same size and fit inside the 28px button', () => {
    const outlined = css.match(/\.decision-btn__icon svg \{[^}]*\}/)?.[0] ?? '';
    expect(outlined).toContain('width: 17px');
    expect(outlined).toContain('height: 17px');
    const solid = css.match(/\.decision-btn--primary \.decision-btn__icon svg \{[^}]*\}/)?.[0] ?? '';
    expect(solid).toContain('width: 16px');
    expect(solid).toContain('height: 16px');
  });

  it('draws Approve and Deny as soft tints with a matching border and glyph, like Pause and Stop, never as solid fills', () => {
    const approve = css.match(/\.decision-btn--approve \{[^}]*\}/)?.[0] ?? '';
    expect(approve).toContain('border-color: color-mix(in srgb, var(--success-base) 60%, transparent)');
    expect(approve).toContain('background: color-mix(in srgb, var(--success-base) 12%, var(--background-primary))');
    expect(approve).toContain('color: color-mix(in srgb, var(--success-base) 75%, var(--text-primary))');
    const deny = css.match(/\.decision-btn--deny \{[^}]*\}/)?.[0] ?? '';
    expect(deny).toContain('border-color: color-mix(in srgb, var(--error-base) 60%, transparent)');
    expect(deny).toContain('background: color-mix(in srgb, var(--error-base) 12%, var(--background-primary))');
    expect(deny).toContain('color: var(--error-base)');
  });

  it('hides the label from view without removing it from the page', () => {
    const rule = css.match(/\.decision-btn__label \{[^}]*\}/)?.[0] ?? '';
    expect(rule).toContain('clip: rect(0 0 0 0)');
    expect(rule).not.toContain('display: none');
  });

  it('draws the stop tone like the follow-up box Stop button: a red border and tint with a dark glyph, red focus ring', () => {
    const rule = css.match(/\.decision-btn--stop \{[^}]*\}/)?.[0] ?? '';
    expect(rule).toContain('border-color: color-mix(in srgb, var(--error-base) 60%, transparent)');
    expect(rule).toContain('background: color-mix(in srgb, var(--error-base) 12%, var(--background-primary))');
    expect(rule).toContain('color: var(--text-primary)');
    expect(css).toMatch(/\.decision-btn--stop:focus-visible \{[^}]*outline-color: var\(--error-base\)/);
    const runControl = readFileSync(resolve(here, '../../styles/components/run-control-composer.css'), 'utf8');
    expect(runControl).toContain('border: var(--border-thin) solid color-mix(in srgb, var(--error-base) 60%, transparent)');
  });

  it('uses the stop tone, not a blue neutral one, for every button that ends the task or a delegation', () => {
    for (const file of ['../ApprovalOverlay.tsx', '../ApprovalSetOverlay.tsx', '../approval/ApprovalDock.tsx', '../CheckpointFlow.tsx']) {
      const source = readFileSync(resolve(here, file), 'utf8');
      expect(source, file).toMatch(/tone="stop"\s+icon=\{<StopCircleIcon \/>\}/);
      expect(source, file).not.toMatch(/tone="neutral"\s+icon=\{<StopCircleIcon \/>\}/);
    }
  });
});
