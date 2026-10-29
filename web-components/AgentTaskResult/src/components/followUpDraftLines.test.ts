// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import { addDraftLine, draftLinesOf, hasDraftLine, removeDraftLine } from './followUpDraftLines';

function editorWith(html: string): HTMLDivElement {
  const editor = document.createElement('div');
  editor.innerHTML = html;
  return editor;
}

describe('draft line helpers', () => {
  it('reads trimmed, non-blank lines', () => {
    expect(draftLinesOf('  one \n\n two\r\nthree')).toEqual(['one', 'two', 'three']);
    expect(draftLinesOf('')).toEqual([]);
  });

  it('matches whole lines only', () => {
    expect(hasDraftLine('Draft a reply\nArchive them', 'Archive them')).toBe(true);
    expect(hasDraftLine('Draft a reply, then archive them', 'Archive them')).toBe(false);
    expect(hasDraftLine('anything', '   ')).toBe(false);
  });

  it('adds each line as its own block after what the reader already wrote', () => {
    const editor = editorWith('My own note');
    expect(addDraftLine(editor, 'Draft a reply')).toBe(true);
    expect(addDraftLine(editor, 'Archive them')).toBe(true);
    expect(Array.from(editor.childNodes).map(node => node.textContent)).toEqual(['My own note', 'Draft a reply', 'Archive them']);
  });

  it('starts an untouched box clean, even if it holds an empty line', () => {
    const editor = editorWith('<div><br></div>');
    addDraftLine(editor, 'Draft a reply');
    expect(editor.innerHTML).toBe('<div>Draft a reply</div>');
  });

  it('does not add a line twice or add a blank one', () => {
    const editor = editorWith('<div>Draft a reply</div>');
    expect(addDraftLine(editor, 'Draft a reply')).toBe(false);
    expect(addDraftLine(editor, '   ')).toBe(false);
    expect(editor.childNodes).toHaveLength(1);
  });

  it('keeps lines made of special characters intact', () => {
    const editor = editorWith('');
    addDraftLine(editor, '<b>Reply</b> & "archive" it');
    expect(editor.textContent).toBe('<b>Reply</b> & "archive" it');
    expect(editor.querySelector('b')).toBeNull();
  });

  it('removes only the matching line and keeps the reader\'s own text and formatting', () => {
    const editor = editorWith('<div><b>My note</b></div><div>Draft a reply</div><div>Archive them</div>');
    expect(removeDraftLine(editor, 'Draft a reply')).toBe(true);
    expect(editor.innerHTML).toBe('<div><b>My note</b></div><div>Archive them</div>');
  });

  it('leaves the box empty, so its placeholder shows, once the last line goes', () => {
    const editor = editorWith('<div>Draft a reply</div>');
    expect(removeDraftLine(editor, 'Draft a reply')).toBe(true);
    expect(editor.innerHTML).toBe('');
  });

  it('reports false when there is nothing to remove', () => {
    const editor = editorWith('<div>Something else</div>');
    expect(removeDraftLine(editor, 'Draft a reply')).toBe(false);
    expect(editor.innerHTML).toBe('<div>Something else</div>');
  });

  it('never wipes an image when the only text is gone', () => {
    const editor = editorWith('<div><img alt="x"></div><div>Draft a reply</div>');
    removeDraftLine(editor, 'Draft a reply');
    expect(editor.querySelector('img')).not.toBeNull();
  });
});
