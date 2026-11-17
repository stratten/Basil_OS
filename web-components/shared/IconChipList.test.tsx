// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IconChipList, { type IconChipEntry } from './IconChipList';

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

function render(element: React.ReactElement) {
  act(() => root.render(element));
}

const entries: IconChipEntry[] = [
  { key: 'a', name: 'Linear', note: 'needs signing in again', iconSources: ['data:image/png;base64,AAA'], kind: 'connection' },
  { key: 'b', name: 'Basil', lockedLabel: 'Required', kind: 'app' },
];

describe('IconChipList', () => {
  it('draws one chip per entry with its name, note and kind', () => {
    render(<IconChipList groupLabel="Connections" entries={entries} onRemove={vi.fn()} />);
    const group = container.querySelector('[role="group"]')!;
    expect(group.getAttribute('aria-label')).toBe('Connections');
    const chips = Array.from(container.querySelectorAll('.icon-chip'));
    expect(chips.map(chip => chip.querySelector('.icon-chip__name')?.textContent)).toEqual(['Linear', 'Basil']);
    expect(chips[0].querySelector('.icon-chip__note')?.textContent).toBe('needs signing in again');
    expect(chips[0].classList.contains('has-note')).toBe(true);
    expect(chips.map(chip => chip.getAttribute('data-chip-kind'))).toEqual(['connection', 'app']);
  });

  it('removes through the button and names it, and shows a locked word instead of a button', () => {
    const onRemove = vi.fn();
    render(<IconChipList groupLabel="Apps" entries={entries} onRemove={onRemove} />);
    const remove = container.querySelectorAll<HTMLButtonElement>('.icon-chip__remove');
    expect(remove).toHaveLength(1);
    expect(remove[0].getAttribute('aria-label')).toBe('Remove Linear');
    act(() => remove[0].dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(onRemove).toHaveBeenCalledWith(entries[0], 0);
    expect(container.querySelector('.icon-chip__locked')?.textContent).toBe('Required');
  });

  it('is read-only without onRemove, and disables the buttons when asked', () => {
    render(<IconChipList groupLabel="Apps" entries={[entries[0]]} />);
    expect(container.querySelector('.icon-chip__remove')).toBeNull();
    render(<IconChipList groupLabel="Apps" entries={[entries[0]]} onRemove={vi.fn()} removeDisabled />);
    expect(container.querySelector<HTMLButtonElement>('.icon-chip__remove')!.disabled).toBe(true);
  });

  it('renders nothing when empty, or the empty text when given one', () => {
    render(<IconChipList groupLabel="Apps" entries={[]} />);
    expect(container.innerHTML).toBe('');
    render(<IconChipList groupLabel="Apps" entries={[]} emptyText="No excluded apps selected." />);
    expect(container.querySelector('.icon-chip-list__empty')?.textContent).toBe('No excluded apps selected.');
  });

  it('tries each icon source in order, then the glyph, then the first letter of the name', () => {
    const withGlyph: IconChipEntry = { key: 'c', name: 'Gmail', iconSources: ['data:image/png;base64,ONE', 'data:image/png;base64,TWO'], fallbackIcon: <svg data-testid="plug" />, tile: true };
    render(<IconChipList groupLabel="Connections" entries={[withGlyph]} />);
    const image = () => container.querySelector<HTMLImageElement>('img.icon-chip__image');
    expect(image()!.getAttribute('src')).toBe('data:image/png;base64,ONE');
    expect(container.querySelector('.icon-chip__icon--tile')).not.toBeNull();
    act(() => { image()!.dispatchEvent(new Event('error')); });
    expect(image()!.getAttribute('src')).toBe('data:image/png;base64,TWO');
    act(() => { image()!.dispatchEvent(new Event('error')); });
    expect(image()).toBeNull();
    expect(container.querySelector('[data-testid="plug"]')).not.toBeNull();

    render(<IconChipList groupLabel="Apps" entries={[{ key: 'd', name: 'terminal' }]} />);
    expect(container.querySelector('.icon-chip__icon--initial')?.textContent).toBe('T');
  });
});
