import { useMemo } from 'react';
import { marked } from 'marked';
import { BASIC_MARKDOWN_TAGS, escapeHtmlText, sanitizeMarkdownHtml } from '@shared/markdownSafety';

marked.setOptions({ gfm: true, breaks: true });

export function MeetingMarkdown({ content }: { content: string }) {
  const html = useMemo(() => {
    try {
      return sanitizeMarkdownHtml(marked.parse(content) as string, BASIC_MARKDOWN_TAGS);
    } catch {
      return `<p>${escapeHtmlText(content)}</p>`;
    }
  }, [content]);
  return <div className="meeting-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
