// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import CollapsibleSidebar from './CollapsibleSidebar';

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

function renderSidebar(expanded: boolean) {
  act(() => {
    root.render(
      <CollapsibleSidebar expanded={expanded} className="test-sidebar" ariaLabel="Test history" collapsedContent={<button type="button">Show</button>}>
        <button type="button">Hide</button>
      </CollapsibleSidebar>,
    );
  });
  return container.querySelector<HTMLElement>('aside.basil-collapsible-sidebar')!;
}

describe('CollapsibleSidebar', () => {
  it('marks the expanded layer active and the collapsed layer inert', () => {
    const sidebar = renderSidebar(true);
    expect(sidebar.className).toBe('basil-collapsible-sidebar is-expanded test-sidebar');
    expect(sidebar.getAttribute('aria-label')).toBe('Test history');
    const collapsedLayer = sidebar.querySelector('.basil-collapsible-sidebar__layer--collapsed')!;
    const expandedLayer = sidebar.querySelector('.basil-collapsible-sidebar__layer--expanded')!;
    expect(collapsedLayer.hasAttribute('inert')).toBe(true);
    expect(collapsedLayer.getAttribute('aria-hidden')).toBe('true');
    expect(expandedLayer.hasAttribute('inert')).toBe(false);
    expect(expandedLayer.getAttribute('aria-hidden')).toBe('false');
  });

  it('keeps the same element and both layers mounted when collapsing', () => {
    const expanded = renderSidebar(true);
    const hideButton = expanded.querySelector('.basil-collapsible-sidebar__layer--expanded button');
    const collapsed = renderSidebar(false);
    expect(collapsed).toBe(expanded);
    expect(collapsed.className).toBe('basil-collapsible-sidebar is-collapsed test-sidebar');
    expect(collapsed.querySelector('.basil-collapsible-sidebar__layer--expanded button')).toBe(hideButton);
    expect(collapsed.querySelector('.basil-collapsible-sidebar__layer--expanded')!.hasAttribute('inert')).toBe(true);
    expect(collapsed.querySelector('.basil-collapsible-sidebar__layer--collapsed')!.hasAttribute('inert')).toBe(false);
  });

  it('renders a div root without an accessible name when requested', () => {
    act(() => {
      root.render(<CollapsibleSidebar element="div" expanded collapsedContent={null}>content</CollapsibleSidebar>);
    });
    expect(container.firstElementChild?.tagName).toBe('DIV');
    expect(container.firstElementChild?.hasAttribute('aria-label')).toBe(false);
  });
});
