import { useMemo } from 'react';
import { marked } from 'marked';

marked.setOptions({ gfm: true, breaks: true });

const allowedTags = new Set([
  'P', 'H1', 'H2', 'H3', 'H4', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I', 'U', 'CODE', 'PRE', 'BLOCKQUOTE', 'BR', 'A',
]);

function sanitizeMeetingMarkdown(html: string): string {
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

export function MeetingMarkdown({ content }: { content: string }) {
  const html = useMemo(() => {
    try {
      return sanitizeMeetingMarkdown(marked.parse(content) as string);
    } catch {
      return `<p>${content.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    }
  }, [content]);
  return <div className="meeting-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
