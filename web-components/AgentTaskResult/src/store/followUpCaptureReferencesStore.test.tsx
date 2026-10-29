// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  __resetFollowUpCaptureReferencesForTests,
  publishFollowUpCaptureReferences,
  useFollowUpCaptureReferences,
} from './followUpCaptureReferencesStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;
let renderCount = 0;

function Probe() {
  renderCount += 1;
  return <span>{useFollowUpCaptureReferences().join('|')}</span>;
}

describe('followUpCaptureReferencesStore', () => {
  beforeEach(() => {
    renderCount = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root.render(<Probe />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    __resetFollowUpCaptureReferencesForTests();
  });

  it('renders the published paths in order and clears them', () => {
    expect(container.textContent).toBe('');
    act(() => publishFollowUpCaptureReferences(['/tmp/a.pdf', '/tmp/folder']));
    expect(container.textContent).toBe('/tmp/a.pdf|/tmp/folder');
    act(() => publishFollowUpCaptureReferences([]));
    expect(container.textContent).toBe('');
  });

  it('does not re-render when the same list is published again', () => {
    act(() => publishFollowUpCaptureReferences(['/tmp/a.pdf']));
    const afterFirst = renderCount;
    act(() => publishFollowUpCaptureReferences(['/tmp/a.pdf']));
    expect(renderCount).toBe(afterFirst);
    act(() => publishFollowUpCaptureReferences([]));
    const afterClear = renderCount;
    act(() => publishFollowUpCaptureReferences([]));
    expect(renderCount).toBe(afterClear);
  });
});
