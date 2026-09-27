import { useMemo } from 'react';
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
    if (!url.startsWith('https://') && !url.startsWith('http://')) return;
    const handlers = window.webkit?.messageHandlers;
    if (handlers?.assistantSessionBridge) {
      handlers.assistantSessionBridge.postMessage({ type: 'openExternalUrl', url });
    } else {
      handlers?.assistantOutputHistoryBridge?.postMessage({ type: 'openHistoryExternalUrl', url });
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
