import { useMemo, type MouseEvent } from 'react';
import { marked } from 'marked';
import { BASIC_MARKDOWN_TAGS, escapeHtmlText, externalLinkTarget, sanitizeMarkdownHtml } from '@shared/markdownSafety';
import { openExternalUrl } from '../bridge/meetingBridge';

marked.setOptions({ gfm: true, breaks: true });

export function MeetingMarkdown({ content }: { content: string }) {
  const html = useMemo(() => {
    try {
      return sanitizeMarkdownHtml(marked.parse(content) as string, BASIC_MARKDOWN_TAGS);
    } catch {
      return `<p>${escapeHtmlText(content)}</p>`;
    }
  }, [content]);

  const openLink = (event: MouseEvent<HTMLDivElement>) => {
    const anchor = (event.target as HTMLElement).closest('a');
    const href = anchor?.getAttribute('href');
    if (!href) return;
    event.preventDefault();
    const target = externalLinkTarget(href, { allowMailto: true });
    if (target) openExternalUrl(target);
  };

  return <div className="meeting-markdown" dangerouslySetInnerHTML={{ __html: html }} onClick={openLink} />;
}
