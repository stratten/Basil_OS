import { useMemo, useRef, useEffect, useCallback } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { ARTIFACT_MARKDOWN_PURIFY_OPTIONS, escapeHtmlText, normalizeMarkdownBullets } from '@shared/text/markdownSafety';
import { COPY_FEEDBACK_MS } from '@shared/useCopyFeedback';
import { copyToClipboard, openFile, openExternalUrl } from '../services/bridge';
import { CHECK_ICON_MARKUP, COPY_ICON_MARKUP } from './result/copyIconMarkup';
import hljs from 'highlight.js/lib/core';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import python from 'highlight.js/lib/languages/python';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import swift from 'highlight.js/lib/languages/swift';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import sql from 'highlight.js/lib/languages/sql';
import yaml from 'highlight.js/lib/languages/yaml';
import markdown from 'highlight.js/lib/languages/markdown';

hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('js', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('ts', typescript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('py', python);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sh', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('json', json);
hljs.registerLanguage('swift', swift);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('html', xml);
hljs.registerLanguage('css', css);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('yml', yaml);
hljs.registerLanguage('markdown', markdown);
hljs.registerLanguage('md', markdown);

marked.setOptions({
  gfm: true,
  breaks: true,
});

const renderer = new marked.Renderer();
renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
  let highlighted: string;
  if (lang && hljs.getLanguage(lang)) {
    highlighted = hljs.highlight(text, { language: lang }).value;
  } else {
    highlighted = hljs.highlightAuto(text).value;
  }
  const languageClass = (lang || 'plaintext').replace(/[^A-Za-z0-9_+-]/g, '') || 'plaintext';
  const label = lang ? languageClass : '';
  return copyBlock(`<pre><code class="hljs language-${languageClass}">${highlighted}</code></pre>`, 'Copy code', label);
};
renderer.blockquote = function ({ tokens }) {
  return copyBlock(`<blockquote>${this.parser.parse(tokens)}</blockquote>`, 'Copy quote', 'Quote');
};

/** Wraps a fenced code block or quote with its own copy button; the click handler finds the block beside the button. */
function copyBlock(blockHtml: string, copyLabel: string, caption: string): string {
  const captionHtml = caption ? `<span class="markdown-copy-caption">${escapeHtmlText(caption)}</span>` : '<span></span>';
  return `<div class="markdown-copy-block"><div class="markdown-copy-bar">${captionHtml}<button type="button" class="markdown-copy-button" data-copy-label="${copyLabel}" aria-label="${copyLabel}" title="${copyLabel}">${COPY_ICON_MARKUP}</button></div>${blockHtml}</div>`;
}

/** The text of a fenced block or quote without any copy buttons nested inside it. */
function copyableText(block: Element): string {
  const clone = block.cloneNode(true) as Element;
  clone.querySelectorAll('.markdown-copy-bar').forEach(bar => bar.remove());
  return (clone.textContent || '').replace(/\s+$/, '');
}

interface Props {
  content: string;
  isStreaming?: boolean;
  variant?: 'checkpoint' | 'request';
}

export default function MarkdownRenderer({ content, isStreaming, variant }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);

  const html = useMemo(() => {
    const normalized = normalizeMarkdownBullets(content);
    try {
      return DOMPurify.sanitize(marked.parse(normalized, { renderer }) as string, ARTIFACT_MARKDOWN_PURIFY_OPTIONS);
    } catch {
      return `<p>${escapeHtmlText(normalized)}</p>`;
    }
  }, [content]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    const copyButton = (e.target as HTMLElement).closest<HTMLElement>('.markdown-copy-button');
    if (copyButton) {
      e.preventDefault();
      e.stopPropagation();
      const block = copyButton.closest('.markdown-copy-block')?.querySelector(':scope > pre, :scope > blockquote');
      if (!block) return;
      copyToClipboard(copyableText(block));
      // The check mark replaces the icon for the same moment the other copy buttons show theirs, and the label says so for assistive technology.
      const copyLabel = copyButton.getAttribute('data-copy-label') || 'Copy';
      copyButton.innerHTML = CHECK_ICON_MARKUP;
      copyButton.setAttribute('aria-label', `${copyLabel} copied`);
      copyButton.title = `${copyLabel} copied`;
      window.setTimeout(() => {
        if (!copyButton.isConnected) return;
        copyButton.innerHTML = COPY_ICON_MARKUP;
        copyButton.setAttribute('aria-label', copyLabel);
        copyButton.title = copyLabel;
      }, COPY_FEEDBACK_MS);
      return;
    }
    const target = (e.target as HTMLElement).closest('a');
    if (!target) return;
    const href = target.getAttribute('href');
    if (!href) return;

    e.preventDefault();
    e.stopPropagation();

    if (href.startsWith('http://') || href.startsWith('https://')) {
      openExternalUrl(href);
    } else {
      openFile(href);
    }
  }, []);

  useEffect(() => {
    if (isStreaming && containerRef.current && content.length > prevLengthRef.current) {
      const el = containerRef.current;
      el.scrollTop = el.scrollHeight;
    }
    prevLengthRef.current = content.length;
  }, [content, isStreaming]);

  return (
    <div
      ref={containerRef}
      className={`result-section${variant ? ` result-section--${variant}` : ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={handleClick}
    />
  );
}
