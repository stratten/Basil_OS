import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.setOptions({ gfm: true, breaks: true });

/** Renders the same full Markdown surface as the Swift oracle while removing executable model-provided HTML. */
export function markdownToHTML(markdown: string): string {
  const normalized = markdown.replace(/^[•●]\s/gm, '- ');
  return DOMPurify.sanitize(marked.parse(normalized) as string, {
    FORBID_TAGS: ['audio', 'iframe', 'img', 'source', 'style', 'video'],
    FORBID_ATTR: ['style'],
  });
}
