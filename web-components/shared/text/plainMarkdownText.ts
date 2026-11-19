const CODE_PLACEHOLDER = '\u0000';

/**
 * Flattens markdown into a single line of plain text for titles, previews, and other surfaces that render text rather than markdown. Previews are often truncated server-side, so unpaired `**`, `__`, `~~`, and backticks left by the cut are removed as well.
 */
export function plainMarkdownText(markdown: string | null | undefined): string {
  if (!markdown) return '';

  const codeSpans: string[] = [];
  const protect = (content: string) => `${CODE_PLACEHOLDER}${codeSpans.push(content) - 1}${CODE_PLACEHOLDER}`;

  return markdown
    .replace(/^\s{0,3}(`{3,}|~{3,})[^\n]*$/gm, '')
    .replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (_match, _ticks: string, content: string) => protect(content.trim()))
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<\/?[a-zA-Z][^>\n]*>/g, ' ')
    .replace(/^\s{0,3}(?:[-*_]\s*){3,}$/gm, '')
    .replace(/^\s{0,3}(?:>\s?)*(?:#{1,6}\s+|[-+*]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)?/gm, '')
    .replace(/(\*\*|__|~~)(?=\S)([\s\S]*?\S)\1/g, '$2')
    .replace(/(^|[^\\*])\*(?=\S)([^*\n]*?\S)\*(?!\*)/g, '$1$2')
    .replace(/(^|[^\\\w])_(?=\S)([^_\n]*?\S)_(?!\w)/g, '$1$2')
    .replace(/(^|[^\\])(\*\*|__|~~|`+)/g, '$1')
    .replace(/\\([\\`*_{}[\]()#+\-.!>~|])/g, '$1')
    .replace(new RegExp(`${CODE_PLACEHOLDER}(\\d+)${CODE_PLACEHOLDER}`, 'g'), (_match, index: string) => codeSpans[Number(index)] ?? '')
    .replace(/\s+/g, ' ')
    .trim();
}
