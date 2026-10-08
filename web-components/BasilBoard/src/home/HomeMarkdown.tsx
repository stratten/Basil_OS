import { useMemo } from 'react';
import { marked } from 'marked';
import { openExternalUrl } from '../services/bridge';
import {
  EXTENDED_MARKDOWN_TAGS,
  escapeHtmlText,
  externalLinkTarget,
  normalizeMarkdownBullets,
  sanitizeMarkdownHtml,
} from '@shared/markdownSafety';

marked.setOptions({
  gfm: true,
  breaks: true,
});

interface HomeMarkdownProps {
  content: string;
  variant: 'user' | 'assistant' | 'task';
}

export default function HomeMarkdown({ content, variant }: HomeMarkdownProps) {
  const html = useMemo(() => {
    const normalized = normalizeMarkdownBullets(content);
    try {
      return sanitizeMarkdownHtml(marked.parse(normalized) as string, EXTENDED_MARKDOWN_TAGS);
    } catch {
      return `<p>${escapeHtmlText(normalized)}</p>`;
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
        event.preventDefault();
        const href = externalLinkTarget(anchor.getAttribute('href'), { allowMailto: true });
        if (href) openExternalUrl(href);
      }}
    />
  );
}
