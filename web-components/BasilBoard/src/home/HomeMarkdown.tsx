import { useMemo } from 'react';
import { marked } from 'marked';
import { openExternalUrl } from '../services/bridge';

marked.setOptions({
  gfm: true,
  breaks: true,
});

const allowedTags = new Set([
  'P', 'H1', 'H2', 'H3', 'H4', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I', 'U', 'CODE', 'PRE', 'BLOCKQUOTE', 'BR', 'A',
]);

function sanitizeHomeMarkdown(html: string): string {
  const document = new DOMParser().parseFromString(html, 'text/html');
  for (const element of Array.from(document.body.querySelectorAll('*'))) {
    if (!allowedTags.has(element.tagName)) {
      element.replaceWith(...Array.from(element.childNodes));
      continue;
    }
    for (const attribute of Array.from(element.attributes)) {
      if (element.tagName !== 'A' || attribute.name !== 'href') {
        element.removeAttribute(attribute.name);
      }
    }
    if (element.tagName === 'A') {
      const href = element.getAttribute('href') ?? '';
      if (!/^(https?:|mailto:)/i.test(href)) {
        element.removeAttribute('href');
      }
    }
  }
  return document.body.innerHTML;
}

interface HomeMarkdownProps {
  content: string;
  variant: 'user' | 'assistant' | 'task';
}

export default function HomeMarkdown({ content, variant }: HomeMarkdownProps) {
  const html = useMemo(() => {
    const normalized = content.replace(/^[•●]\s/gm, '- ');
    try {
      return sanitizeHomeMarkdown(marked.parse(normalized) as string);
    } catch {
      return `<p>${normalized.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    }
  }, [content]);

  return (
    <div
      className={`home-markdown home-markdown-${variant}`}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={(event) => {
        const target = event.target as HTMLElement | null;
        const anchor = target?.closest('a');
        if (!anchor) return;
        const href = anchor.getAttribute('href');
        if (!href || !/^(https?:|mailto:)/i.test(href)) {
          event.preventDefault();
          return;
        }
        event.preventDefault();
        openExternalUrl(href);
      }}
    />
  );
}
