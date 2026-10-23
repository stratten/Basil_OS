const HTML_NAMESPACE = 'http://www.w3.org/1999/xhtml';

const EXTERNAL_LINK_PATTERN = /^(https?:\/\/|mailto:)/i;
const HTTP_LINK_PATTERN = /^https?:\/\//i;

/** Elements removed together with everything inside them, so their text never appears as visible content. */
const DROP_WITH_CONTENT_TAGS: ReadonlySet<string> = new Set([
  'SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'TEXTAREA',
]);

/** Prose-only subset used by Notetaker analysis and Paprika task results. */
export const BASIC_MARKDOWN_TAGS: ReadonlySet<string> = new Set([
  'P', 'H1', 'H2', 'H3', 'H4', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I', 'U', 'CODE', 'PRE', 'BLOCKQUOTE', 'BR', 'A',
]);

/** Basic tags plus deeper headings, strikethrough, rules, and tables, used by chat and Home. */
export const EXTENDED_MARKDOWN_TAGS: ReadonlySet<string> = new Set([
  ...BASIC_MARKDOWN_TAGS,
  'H5', 'H6', 'DEL', 'S', 'HR', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD',
]);

/** DOMPurify options for chat-style surfaces (Assistant Session, Settings writing samples): no media, frames, styles, or images. */
export const CHAT_MARKDOWN_PURIFY_OPTIONS: { FORBID_TAGS: string[]; FORBID_ATTR: string[] } = {
  FORBID_TAGS: ['audio', 'iframe', 'img', 'source', 'style', 'video'],
  FORBID_ATTR: ['style'],
};

/** DOMPurify options for the Agent Task result and file preview, which keep images but forbid forms, frames, styles, and media. */
export const ARTIFACT_MARKDOWN_PURIFY_OPTIONS: { FORBID_TAGS: string[]; FORBID_ATTR: string[] } = {
  FORBID_TAGS: ['audio', 'form', 'iframe', 'source', 'style', 'video'],
  FORBID_ATTR: ['style'],
};

/** Rewrites leading bullet glyphs that models emit (a bullet or black circle followed by whitespace) into Markdown list markers. */
export function normalizeMarkdownBullets(markdown: string): string {
  return markdown.replace(/^[•●]\s/gm, '- ');
}

/** Escapes text so it can be placed inside an HTML element when Markdown parsing fails. */
export function escapeHtmlText(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Returns the href when it may be opened outside the web view (http, https, and optionally mailto), otherwise null. */
export function externalLinkTarget(
  href: string | null | undefined,
  options: { allowMailto: boolean },
): string | null {
  if (!href) return null;
  const pattern = options.allowMailto ? EXTERNAL_LINK_PATTERN : HTTP_LINK_PATTERN;
  return pattern.test(href) ? href : null;
}

/**
 * Allowlist sanitizer for HTML produced by `marked`. Elements outside the allowlist are replaced by their children, executable and embedded elements are removed with their content, elements outside the HTML namespace (SVG, MathML) are removed, every attribute is stripped except `href` on links, and an href survives only when it is http, https, or mailto.
 */
export function sanitizeMarkdownHtml(html: string, allowedTags: ReadonlySet<string>): string {
  const document = new DOMParser().parseFromString(html, 'text/html');
  for (const element of Array.from(document.body.querySelectorAll('*'))) {
    if (!document.body.contains(element)) continue;
    if (element.namespaceURI !== HTML_NAMESPACE || DROP_WITH_CONTENT_TAGS.has(element.tagName)) {
      element.remove();
      continue;
    }
    if (!allowedTags.has(element.tagName)) {
      element.replaceWith(...Array.from(element.childNodes));
      continue;
    }
    for (const attribute of Array.from(element.attributes)) {
      if (element.tagName !== 'A' || attribute.name !== 'href') {
        element.removeAttribute(attribute.name);
      }
    }
    if (element.tagName === 'A' && !EXTERNAL_LINK_PATTERN.test(element.getAttribute('href') ?? '')) {
      element.removeAttribute('href');
    }
  }
  return document.body.innerHTML;
}
