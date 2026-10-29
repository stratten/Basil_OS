import { afterEach, describe, expect, it } from 'vitest';
import { focusEditableAtEnd } from './focusEditableAtEnd';

describe('focusEditableAtEnd', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('focuses the editor and places the caret after its content', () => {
    const editor = document.createElement('div');
    editor.contentEditable = 'true';
    editor.tabIndex = 0;
    editor.innerHTML = 'Draft <strong>text</strong>';
    document.body.append(editor);

    focusEditableAtEnd(editor);

    expect(document.activeElement).toBe(editor);
    const selection = window.getSelection();
    expect(selection?.isCollapsed).toBe(true);
    expect(selection?.anchorNode).toBe(editor);
    expect(selection?.anchorOffset).toBe(editor.childNodes.length);
  });

  it('ignores a missing element', () => {
    expect(() => focusEditableAtEnd(null)).not.toThrow();
  });
});
