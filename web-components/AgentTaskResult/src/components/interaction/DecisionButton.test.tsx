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
        <DecisionButton tone="neutral" icon={<ApproveCircleIcon />} label="Stop task" lead onClick={vi.fn()} />
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

  it('draws icons at 14px like Stop and Pause on outlined buttons and 13px on the solid ones, so the rings look the same size', () => {
    const outlined = css.match(/\.decision-btn__icon svg \{[^}]*\}/)?.[0] ?? '';
    expect(outlined).toContain('width: 14px');
    expect(outlined).toContain('height: 14px');
    const solid = css.match(/\.decision-btn--primary \.decision-btn__icon svg,\s*\.decision-btn--approve \.decision-btn__icon svg \{[^}]*\}/)?.[0] ?? '';
    expect(solid).toContain('width: 13px');
    expect(solid).toContain('height: 13px');
  });

  it('hides the label from view without removing it from the page', () => {
    const rule = css.match(/\.decision-btn__label \{[^}]*\}/)?.[0] ?? '';
    expect(rule).toContain('clip: rect(0 0 0 0)');
    expect(rule).not.toContain('display: none');
  });
});
