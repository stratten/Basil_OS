import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { CHAT_MARKDOWN_PURIFY_OPTIONS, normalizeMarkdownBullets } from '@shared/markdownSafety';

marked.setOptions({ gfm: true, breaks: true });

/** Renders the same full Markdown surface as the Swift oracle while removing executable model-provided HTML. */
export function markdownToHTML(markdown: string): string {
  const normalized = normalizeMarkdownBullets(markdown);
  return DOMPurify.sanitize(marked.parse(normalized) as string, CHAT_MARKDOWN_PURIFY_OPTIONS);
}
