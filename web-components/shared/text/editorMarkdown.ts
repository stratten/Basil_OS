import { externalLinkTarget } from './markdownSafety';

type MarkdownBlockKind = 'line' | 'paragraph' | 'block';

interface MarkdownBlock {
  kind: MarkdownBlockKind;
  text: string;
}

interface InlineState {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
}

interface StyleFlags {
  bold?: boolean;
  boldOff?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  code?: boolean;
}

const PLAIN_STATE: InlineState = { bold: false, italic: false, underline: false, strike: false };

const BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'blockquote', 'div', 'dl', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'ul',
]);

const CODE_TAGS = new Set(['code', 'kbd', 'samp', 'tt']);
const IGNORED_TAGS = new Set(['img', 'script', 'style', 'meta', 'link', 'title']);
const HREF_ESCAPES: Record<string, string> = { '(': '%28', ')': '%29', '<': '%3C', '>': '%3E' };

function escapeMarkdownText(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/([`*_{}[\]<>~|])/g, '\\$1');
}

export function plainTextToDisplayMarkdown(text: string): string {
  return escapeMarkdownText(text);
}

function normalizeTextNode(text: string): string {
  return text.replace(/\u00a0/g, ' ').replace(/[ \t\r]*\n\s*/g, ' ');
}

function isFormattingWhitespace(text: string): boolean {
  return /^\s*$/.test(text) && text.includes('\n');
}

function escapeLineStart(line: string): string {
  return line.replace(
    /^(\s*)(#{1,6}(?=\s|$)|>|[-+](?=\s)|\d+(?=[.)]\s))/,
    (_match, indent: string, marker: string) => (/^\d+$/.test(marker) ? `${indent}${marker}\\` : `${indent}\\${marker}`),
  );
}

function escapeLineStarts(text: string): string {
  return text.split('\n').map(escapeLineStart).join('\n');
}

function styleFlags(element: HTMLElement): StyleFlags {
  const style = (element as { style?: CSSStyleDeclaration }).style;
  if (!style) return {};
  const weight = style.fontWeight || '';
  const numericWeight = Number.parseInt(weight, 10);
  const decoration = `${style.textDecoration || ''} ${style.textDecorationLine || ''}`;
  return {
    bold: weight === 'bold' || weight === 'bolder' || (!Number.isNaN(numericWeight) && numericWeight >= 600),
    boldOff: weight === 'normal' || weight === 'lighter' || (!Number.isNaN(numericWeight) && numericWeight < 600),
    italic: style.fontStyle === 'italic' || style.fontStyle === 'oblique',
    underline: decoration.includes('underline'),
    strike: decoration.includes('line-through'),
    code: /\b(mono|monospace|courier|menlo|consolas|monaco)\b/i.test(style.fontFamily || ''),
  };
}

function wrapInline(content: string, open: string, close = open): string {
  const match = /^(\s*)([\s\S]*?)(\s*)$/.exec(content);
  if (!match || !match[2]) return content;
  return `${match[1]}${open}${match[2]}${close}${match[3]}`;
}

function longestBacktickRun(text: string): number {
  return Math.max(0, ...(text.match(/`+/g) ?? []).map((run) => run.length));
}

function codeSpan(text: string): string {
  const value = normalizeTextNode(text);
  if (!value.trim()) return '';
  const fence = '`'.repeat(longestBacktickRun(value) + 1);
  const padded = value.startsWith('`') || value.endsWith('`') ? ` ${value} ` : value;
  return `${fence}${padded}${fence}`;
}

function safeLinkHref(element: HTMLElement): string | undefined {
  const href = element.getAttribute?.('href')?.trim();
  if (!href || !externalLinkTarget(href, { allowMailto: true })) return undefined;
  return href.replace(/[\s()<>]/g, (character) => HREF_ESCAPES[character] ?? encodeURIComponent(character));
}

function inlineMarkdown(node: Node, inherited: InlineState = PLAIN_STATE): string {
  if (node.nodeType === 3) return escapeMarkdownText(normalizeTextNode(node.textContent || ''));
  if (node.nodeType !== 1) return '';
  const element = node as HTMLElement;
  const tag = element.tagName.toLowerCase();
  if (tag === 'br') return '\n';
  if (IGNORED_TAGS.has(tag)) return '';
  if (CODE_TAGS.has(tag)) return codeSpan(element.textContent || '');
  const flags = styleFlags(element);
  if (flags.code) return codeSpan(element.textContent || '');
  const state: InlineState = {
    bold: inherited.bold || (tag === 'b' || tag === 'strong' ? !flags.boldOff : Boolean(flags.bold)),
    italic: inherited.italic || tag === 'i' || tag === 'em' || Boolean(flags.italic),
    underline: inherited.underline || tag === 'u' || tag === 'ins' || Boolean(flags.underline),
    strike: inherited.strike || tag === 's' || tag === 'strike' || tag === 'del' || Boolean(flags.strike),
  };
  let content = Array.from(element.childNodes).map((child) => inlineMarkdown(child, state)).join('');
  if (BLOCK_TAGS.has(tag) && content && !content.endsWith('\n')) content = `${content}\n`;
  if (tag === 'a') {
    const href = safeLinkHref(element);
    if (href && content.trim()) content = `[${content}](${href})`;
  }
  if (state.strike && !inherited.strike) content = wrapInline(content, '~~');
  if (state.underline && !inherited.underline) content = wrapInline(content, '<u>', '</u>');
  if (state.italic && !inherited.italic) content = wrapInline(content, '*');
  if (state.bold && !inherited.bold) content = wrapInline(content, '**');
  return content;
}

function inlineText(element: HTMLElement): string {
  return Array.from(element.childNodes)
    .map((child) => inlineMarkdown(child))
    .join('')
    .replace(/\n$/, '');
}

function listMarkdown(list: HTMLElement, indent = ''): string {
  const ordered = list.tagName.toLowerCase() === 'ol';
  return Array.from(list.children)
    .filter((child) => child.tagName.toLowerCase() === 'li')
    .map((item, index) => {
      const element = item as HTMLElement;
      const nested = Array.from(element.children).filter((child) => ['ol', 'ul'].includes(child.tagName.toLowerCase())) as HTMLElement[];
      const content = Array.from(element.childNodes)
        .filter((child) => !nested.includes(child as HTMLElement))
        .map((child) => inlineMarkdown(child))
        .join('')
        .trim()
        .split('\n')
        .join(`\n${indent}  `);
      return `${indent}${ordered ? `${index + 1}.` : '-'} ${content}\n${nested.map((child) => listMarkdown(child, `${indent}  `)).join('')}`;
    })
    .join('');
}

function preformattedText(node: Node): string {
  if (node.nodeType === 3) return (node.textContent || '').replace(/\u00a0/g, ' ');
  if (node.nodeType !== 1) return '';
  const element = node as HTMLElement;
  const tag = element.tagName.toLowerCase();
  if (tag === 'br') return '\n';
  const text = Array.from(element.childNodes).map((child) => preformattedText(child)).join('');
  return tag === 'div' || tag === 'p' ? `${text}\n` : text;
}

function fencedCode(element: HTMLElement): string {
  const text = preformattedText(element).replace(/^\n+/, '').replace(/\n+$/, '');
  const fence = '`'.repeat(Math.max(2, longestBacktickRun(text)) + 1);
  return `${fence}\n${text}\n${fence}`;
}

function tableRows(table: HTMLElement): HTMLElement[] {
  const rows: HTMLElement[] = [];
  const visit = (element: HTMLElement) => {
    for (const child of Array.from(element.children) as HTMLElement[]) {
      const tag = child.tagName.toLowerCase();
      if (tag === 'tr') rows.push(child);
      else if (tag === 'thead' || tag === 'tbody' || tag === 'tfoot') visit(child);
    }
  };
  visit(table);
  return rows;
}

function tableMarkdown(table: HTMLElement): string {
  const rows = tableRows(table).map((row) => (Array.from(row.children) as HTMLElement[])
    .filter((cell) => ['td', 'th'].includes(cell.tagName.toLowerCase()))
    .map((cell) => inlineText(cell).replace(/\s*\n\s*/g, ' ').trim()));
  const width = Math.max(0, ...rows.map((row) => row.length));
  if (rows.length === 0 || width === 0) return '';
  const line = (row: string[]) => `| ${[...row, ...Array<string>(width - row.length).fill('')].join(' | ')} |`;
  return [line(rows[0]), line(Array<string>(width).fill('---')), ...rows.slice(1).map(line)].join('\n');
}

function collectBlocks(nodes: readonly Node[], blocks: MarkdownBlock[]): void {
  let pending = '';
  let hasPending = false;
  const flush = () => {
    if (!hasPending) return;
    blocks.push({ kind: 'line', text: pending });
    pending = '';
    hasPending = false;
  };
  for (const node of nodes) {
    if (node.nodeType === 3) {
      const raw = node.textContent || '';
      if (isFormattingWhitespace(raw)) continue;
      pending += escapeMarkdownText(normalizeTextNode(raw));
      hasPending = true;
      continue;
    }
    if (node.nodeType !== 1) continue;
    const element = node as HTMLElement;
    const tag = element.tagName.toLowerCase();
    if (tag === 'br') {
      blocks.push({ kind: 'line', text: pending });
      pending = '';
      hasPending = false;
      continue;
    }
    if (!BLOCK_TAGS.has(tag)) {
      pending += inlineMarkdown(element);
      hasPending = true;
      continue;
    }
    flush();
    const heading = /^h([1-6])$/.exec(tag);
    if (heading) {
      const title = inlineText(element).replace(/\s*\n\s*/g, ' ').trim();
      if (title) blocks.push({ kind: 'block', text: `${'#'.repeat(Number(heading[1]))} ${title}` });
      continue;
    }
    switch (tag) {
      case 'pre':
        blocks.push({ kind: 'block', text: fencedCode(element) });
        break;
      case 'ul':
      case 'ol':
        blocks.push({ kind: 'block', text: listMarkdown(element).replace(/\n+$/, '') });
        break;
      case 'table': {
        const table = tableMarkdown(element);
        if (table) blocks.push({ kind: 'block', text: table });
        break;
      }
      case 'hr':
        blocks.push({ kind: 'block', text: '---' });
        break;
      case 'blockquote': {
        const innerBlocks: MarkdownBlock[] = [];
        collectBlocks(Array.from(element.childNodes), innerBlocks);
        const inner = blocksToMarkdown(innerBlocks);
        if (inner) blocks.push({ kind: 'block', text: inner.split('\n').map((line) => (line ? `> ${line}` : '>')).join('\n') });
        break;
      }
      case 'p':
        blocks.push({ kind: 'paragraph', text: inlineText(element) });
        break;
      default:
        if (Array.from(element.children).some((child) => BLOCK_TAGS.has(child.tagName.toLowerCase()))) {
          collectBlocks(Array.from(element.childNodes), blocks);
        } else {
          blocks.push({ kind: 'line', text: inlineText(element) });
        }
    }
  }
  flush();
}

function blocksToMarkdown(blocks: readonly MarkdownBlock[]): string {
  let markdown = '';
  let previous: MarkdownBlock | undefined;
  for (const block of blocks) {
    const text = block.kind === 'block' ? block.text : escapeLineStarts(block.text);
    if (previous === undefined) markdown = text;
    else markdown += (block.kind === 'line' && previous.kind === 'line' ? '\n' : '\n\n') + text;
    previous = block;
  }
  return markdown.replace(/\n{3,}/g, '\n\n').trim();
}

export function editorHtmlToDisplayMarkdown(editor: HTMLElement): string {
  const blocks: MarkdownBlock[] = [];
  collectBlocks(Array.from(editor.childNodes), blocks);
  return blocksToMarkdown(blocks);
}
