import { useMemo } from 'react';
import { externalLinkTarget } from '@shared/markdownSafety';
import { postToSwiftHandler } from '@shared/swiftBridge';
import { markdownToHTML } from '../lib/markdownToHtml';

export function MarkdownView({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const html = useMemo(() => markdownToHTML(content), [content]);

  const openLink = (event: React.MouseEvent<HTMLDivElement>) => {
    const anchor = (event.target as HTMLElement).closest('a');
    const url = anchor?.getAttribute('href');
    if (!url) return;
    event.preventDefault();
    if (!externalLinkTarget(url, { allowMailto: false })) return;
    if (!postToSwiftHandler('assistantSessionBridge', { type: 'openExternalUrl', url })) {
      postToSwiftHandler('assistantOutputHistoryBridge', { type: 'openHistoryExternalUrl', url });
    }
  };

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={openLink}
    />
  );
}
