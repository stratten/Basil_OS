const CODE_BLOCK_LINE_TAGS = new Set(['DIV', 'P', 'LI']);
const TOP_LEVEL_BLOCK_TAGS = new Set([
  'DIV', 'P', 'PRE', 'UL', 'OL', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TABLE', 'HR',
]);
const CARET_MARKER = '\uE000';

function codeBlockText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').replace(/\u00a0/g, ' ');
  if (node.nodeName === 'BR') return '\n';
  const text = Array.from(node.childNodes).map(codeBlockText).join('');
  return CODE_BLOCK_LINE_TAGS.has(node.nodeName) && !text.endsWith('\n') ? `${text}\n` : text;
}

export function enclosingCodeBlock(node: Node | null, editor: HTMLElement): HTMLElement | null {
  let current: Node | null = node;
  while (current && current !== editor) {
    if (current.nodeName === 'PRE') return current as HTMLElement;
    current = current.parentNode;
  }
  return null;
}

export function editorSelectionRange(editor: HTMLElement): Range | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  return editor.contains(range.commonAncestorContainer) ? range : null;
}

function placeCaret(node: Node, offset: number): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.setStart(node, offset);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function createEmptyLine(): HTMLDivElement {
  const line = document.createElement('div');
  line.append(document.createElement('br'));
  return line;
}

function insertLineAfter(pre: HTMLElement): void {
  const line = createEmptyLine();
  pre.after(line);
  placeCaret(line, 0);
}

// A code block always holds one text node ending in a newline: browsers do not render a pre's final newline, so the
// caret can sit on an empty last line. Returns the caret's offset in that text when a caret range is supplied.
function flattenCodeBlock(pre: HTMLElement, caret?: Range): number | null {
  let marker: Text | null = null;
  if (caret) {
    marker = document.createTextNode(CARET_MARKER);
    const markerRange = caret.cloneRange();
    markerRange.collapse(true);
    markerRange.insertNode(marker);
  }
  let text = codeBlockText(pre);
  let offset: number | null = null;
  if (marker) {
    offset = text.indexOf(CARET_MARKER);
    text = text.replace(CARET_MARKER, '');
  }
  if (!text.endsWith('\n')) text = `${text}\n`;
  pre.replaceChildren(document.createTextNode(text));
  return offset === null ? null : Math.max(0, Math.min(offset, text.length - 1));
}

function codeBlockTextAfterCaret(pre: HTMLElement, caret: Range): string {
  const after = document.createRange();
  after.setStart(caret.endContainer, caret.endOffset);
  after.setEnd(pre, pre.childNodes.length);
  return codeBlockText(after.cloneContents());
}

function codeBlockTextBeforeCaret(pre: HTMLElement, caret: Range): string {
  const before = document.createRange();
  before.setStart(pre, 0);
  before.setEnd(caret.startContainer, caret.startOffset);
  return before.toString();
}

export function unwrapCodeBlock(pre: HTMLElement, caret: Range | null): void {
  const caretOffset = flattenCodeBlock(pre, caret ?? undefined) ?? 0;
  const text = (pre.textContent ?? '').replace(/\n$/, '');
  const lines = text.split('\n').map((lineText) => {
    if (!lineText) return createEmptyLine();
    const line = document.createElement('div');
    line.textContent = lineText;
    return line;
  });
  pre.replaceWith(...lines);
  const before = text.slice(0, caretOffset);
  const lineIndex = Math.min(lines.length - 1, before.split('\n').length - 1);
  const column = before.length - (before.lastIndexOf('\n') + 1);
  const target = lines[lineIndex];
  if (target.firstChild?.nodeType === Node.TEXT_NODE) placeCaret(target.firstChild, column);
  else placeCaret(target, 0);
}

function topLevelUnits(editor: HTMLElement): Node[][] {
  const units: Node[][] = [];
  let inline: Node[] = [];
  for (const node of Array.from(editor.childNodes)) {
    if (node.nodeType === Node.ELEMENT_NODE && TOP_LEVEL_BLOCK_TAGS.has(node.nodeName)) {
      if (inline.length) units.push(inline);
      inline = [];
      units.push([node]);
      continue;
    }
    inline.push(node);
    if (node.nodeName === 'BR') {
      units.push(inline);
      inline = [];
    }
  }
  if (inline.length) units.push(inline);
  return units.filter((unit) => unit.some((node) => node.nodeType !== Node.TEXT_NODE || (node.textContent ?? '').trim()));
}

function isCodeBlockUnit(unit: Node[] | undefined): boolean {
  return !!unit && unit.length === 1 && unit[0].nodeName === 'PRE';
}

export function wrapSelectionInCodeBlock(editor: HTMLElement, range: Range | null): void {
  const units = topLevelUnits(editor);
  const touched = range ? units.filter((unit) => unit.some((node) => range.intersectsNode(node))) : [];
  let first = touched.length ? units.indexOf(touched[0]) : -1;
  let last = touched.length && !range?.collapsed ? units.indexOf(touched[touched.length - 1]) : first;
  const pre = document.createElement('pre');
  if (first < 0) {
    pre.textContent = '\n';
    editor.append(pre);
    placeCaret(pre.firstChild!, 0);
    return;
  }
  while (isCodeBlockUnit(units[first - 1])) first -= 1;
  while (isCodeBlockUnit(units[last + 1])) last += 1;
  const selected = units.slice(first, last + 1);
  const text = selected
    .map((unit) => unit.map(codeBlockText).join('').replace(/\n+$/, ''))
    .join('\n');
  pre.textContent = `${text}\n`;
  selected[0][0].parentNode?.insertBefore(pre, selected[0][0]);
  for (const unit of selected) for (const node of unit) node.parentNode?.removeChild(node);
  placeCaret(pre.firstChild!, text.length);
}

function hasFollowingContent(node: Node): boolean {
  let next = node.nextSibling;
  while (next) {
    if (next.nodeType !== Node.TEXT_NODE || (next.textContent ?? '').trim()) return true;
    next = next.nextSibling;
  }
  return false;
}

function insertCodeBlockLineBreak(pre: HTMLElement, caret: Range): void {
  caret.deleteContents();
  const offset = flattenCodeBlock(pre, caret) ?? 0;
  const text = pre.textContent ?? '\n';
  const before = text.slice(0, offset);
  const after = text.slice(offset);
  if (after === '\n' && (before === '' || before.endsWith('\n'))) {
    const kept = before.replace(/\n$/, '');
    insertLineAfter(pre);
    if (kept) pre.textContent = `${kept}\n`;
    else pre.remove();
    return;
  }
  pre.textContent = `${before}\n${after}`;
  placeCaret(pre.firstChild!, offset + 1);
}

/** Applies Return, Backspace, Down, and Right inside a code block; returns whether the key was handled. */
export function applyCodeBlockKey(key: string, pre: HTMLElement, caret: Range): boolean {
  if (key === 'Enter') {
    insertCodeBlockLineBreak(pre, caret);
    return true;
  }
  if (!caret.collapsed) return false;
  if (key === 'Backspace' && codeBlockTextBeforeCaret(pre, caret) === '') {
    unwrapCodeBlock(pre, caret);
    return true;
  }
  if ((key === 'ArrowDown' || key === 'ArrowRight') && !hasFollowingContent(pre)) {
    const after = codeBlockTextAfterCaret(pre, caret).replace(/\n$/, '');
    const atExit = key === 'ArrowRight' ? after === '' : !after.includes('\n');
    if (!atExit) return false;
    insertLineAfter(pre);
    return true;
  }
  return false;
}
