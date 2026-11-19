/** The non-blank lines of the follow-up box's plain text, trimmed. */
export function draftLinesOf(draft: string): string[] {
  return draft
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line.length > 0);
}

export function hasDraftLine(draft: string, line: string): boolean {
  const wanted = line.trim();
  return wanted.length > 0 && draftLinesOf(draft).includes(wanted);
}

function matchingChildren(editor: HTMLElement, line: string): ChildNode[] {
  const wanted = line.trim();
  return Array.from(editor.childNodes).filter(node => (node.textContent ?? '').trim() === wanted);
}

function isBlank(editor: HTMLElement): boolean {
  return (editor.textContent ?? '').trim().length === 0;
}

/** Adds `line` as its own line at the end of the editor, leaving the reader's own text and formatting alone. Returns false when the line is already there. */
export function addDraftLine(editor: HTMLElement, line: string): boolean {
  const text = line.trim();
  if (!text || matchingChildren(editor, text).length > 0) return false;
  // An untouched box can still hold an empty paragraph or line break; start clean so the first line sits at the top.
  if (isBlank(editor) && !editor.querySelector('img')) editor.replaceChildren();
  const row = editor.ownerDocument.createElement('div');
  row.textContent = text;
  editor.appendChild(row);
  return true;
}

/** Removes every line that is exactly `line`, leaving everything else the reader wrote. Returns false when it was not there. */
export function removeDraftLine(editor: HTMLElement, line: string): boolean {
  const matches = matchingChildren(editor, line);
  if (matches.length === 0) return false;
  matches.forEach(node => node.remove());
  // Dropping the last line should show the placeholder again rather than leave an empty block behind.
  if (isBlank(editor) && !editor.querySelector('img')) editor.replaceChildren();
  return true;
}
