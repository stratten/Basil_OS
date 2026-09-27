import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';

describe('ReasoningModelPicker', () => {
  it('renders its menu in a fixed-position document portal', () => {
    const onModelChange = vi.fn();
    render(
      <ReasoningModelPicker
        models={[{ id: 'local-1', name: 'Local one', category: 'local' }]}
        selectedModelId="local-1"
        disabled={false}
        onModelChange={onModelChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));

    const menu = screen.getByRole('listbox', { name: 'Reasoning models' });
    expect(menu.parentElement).toBe(document.body);
    expect(menu).toHaveStyle({ position: 'fixed' });
    fireEvent.click(screen.getByRole('option', { name: 'Local one' }));
    expect(onModelChange).toHaveBeenCalledWith('local-1');
  });

  it('anchors an upward menu four pixels above the measured menu height', () => {
    const originalInnerHeight = window.innerHeight;
    const originalGetBoundingClientRect = Element.prototype.getBoundingClientRect;
    window.innerHeight = 360;
    Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
      if ((this as HTMLElement).getAttribute('aria-haspopup') === 'listbox') {
        return { left: 100, top: 300, right: 240, bottom: 324, width: 140, height: 24, x: 100, y: 300, toJSON() { return {}; } } as DOMRect;
      }
      if ((this as HTMLElement).getAttribute('role') === 'listbox') {
        return { left: 0, top: 0, right: 0, bottom: 120, width: 200, height: 120, x: 0, y: 0, toJSON() { return {}; } } as DOMRect;
      }
      return originalGetBoundingClientRect.call(this);
    };

    try {
      render(
        <ReasoningModelPicker
          models={[{ id: 'local-1', name: 'Local one', category: 'local' }]}
          selectedModelId="local-1"
          disabled={false}
          onModelChange={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByRole('button', { name: 'Reasoning model' }));
      expect(screen.getByRole('listbox', { name: 'Reasoning models' })).toHaveStyle({ top: '176px' });
    } finally {
      window.innerHeight = originalInnerHeight;
      Element.prototype.getBoundingClientRect = originalGetBoundingClientRect;
    }
  });
});
