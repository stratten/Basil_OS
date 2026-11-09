// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../services/bridge';
import { useFilesPickedHandler } from '../services/useFilesPickedHandler';
import { SurfaceStack } from './AgentTaskResultBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Stands in for TextFollowUp, RunControlComposer, and AttachedFilesEditor, which all receive dropped files through this hook.
function DropTarget({ name, received }: { name: string; received: string[] }) {
  useFilesPickedHandler((paths) => {
    received.push(`${name}:${paths.join(',')}`);
  });
  return <span>{name}</span>;
}

function drop(paths: string[]) {
  act(() => {
    window.basilAgentTask?.onFilesPicked(paths);
  });
}

describe('files dropped while one surface replaces another', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('delivers a drop to the scheduled form, not to the regular task surface that is leaving', () => {
    const received: string[] = [];
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1"><DropTarget name="task-composer" received={received} /></SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="scheduled:create"><DropTarget name="scheduled-form" received={received} /></SurfaceStack>);
    });

    expect(container.querySelector('[data-presence-phase="exiting"]')).not.toBeNull();
    drop(['/tmp/folder']);

    expect(received).toEqual(['scheduled-form:/tmp/folder']);
    act(() => root.unmount());
  });

  it('keeps delivering to the scheduled form after the leaving surface has finished leaving', () => {
    const received: string[] = [];
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1"><DropTarget name="task-composer" received={received} /></SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="scheduled:create"><DropTarget name="scheduled-form" received={received} /></SurfaceStack>);
    });
    const outgoing = container.querySelector('[data-presence-phase="exiting"]') as HTMLElement;
    act(() => {
      outgoing.dispatchEvent(new TransitionEvent('transitionend', { bubbles: true, propertyName: 'opacity' }));
    });
    expect(container.querySelector('[data-presence-phase="exiting"]')).toBeNull();

    drop(['/tmp/report.pdf']);

    expect(received).toEqual(['scheduled-form:/tmp/report.pdf']);
    act(() => root.unmount());
  });

  it('delivers a drop to the newly opened regular task, not the one it replaced', () => {
    const received: string[] = [];
    const container = document.createElement('div');
    const root = createRoot(container);

    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:1"><DropTarget name="old-task" received={received} /></SurfaceStack>);
    });
    act(() => {
      root.render(<SurfaceStack surfaceKey="agent:2"><DropTarget name="new-task" received={received} /></SurfaceStack>);
    });

    drop(['/tmp/notes.txt']);

    expect(received).toEqual(['new-task:/tmp/notes.txt']);
    act(() => root.unmount());
  });
});
