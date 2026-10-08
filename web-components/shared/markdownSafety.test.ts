// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import {
  ARTIFACT_MARKDOWN_PURIFY_OPTIONS,
  BASIC_MARKDOWN_TAGS,
  CHAT_MARKDOWN_PURIFY_OPTIONS,
  EXTENDED_MARKDOWN_TAGS,
  escapeHtmlText,
  externalLinkTarget,
  normalizeMarkdownBullets,
  sanitizeMarkdownHtml,
} from './markdownSafety';

function sanitizeBasic(html: string): string {
  return sanitizeMarkdownHtml(html, BASIC_MARKDOWN_TAGS);
}

describe('sanitizeMarkdownHtml', () => {
  it('keeps allowed tags and strips every attribute from them', () => {
    expect(sanitizeBasic('<p class="x" style="color:red" onclick="a()" id="i">hi <strong id="a">bold</strong></p>')).toBe('<p>hi <strong>bold</strong></p>');
  });

  it('keeps only href on links, and only for http, https, and mailto', () => {
    expect(sanitizeBasic('<a href="https://example.com/a?b=1" target="_blank" onclick="x()" rel="opener">ok</a>')).toBe('<a href="https://example.com/a?b=1">ok</a>');
    expect(sanitizeBasic('<a href="HTTP://example.com">up</a>')).toBe('<a href="HTTP://example.com">up</a>');
    expect(sanitizeBasic('<a href="mailto:someone@example.com">mail</a>')).toBe('<a href="mailto:someone@example.com">mail</a>');
  });

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    ' javascript:alert(1)',
    '\u0001javascript:alert(1)',
    'jav&#x09;ascript:alert(1)',
    'java&#x73;cript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    '//evil.example/x',
    '/relative/path',
    'https:example.com',
    '',
  ])('removes the href %j but keeps the link text', (href) => {
    const output = sanitizeBasic(`<a href="${href}">label</a>`);
    const anchor = new DOMParser().parseFromString(output, 'text/html').querySelector('a');
    expect(anchor?.textContent).toBe('label');
    expect(anchor?.hasAttribute('href')).toBe(false);
  });

  it('removes scripts, styles, frames, and similar elements together with their content', () => {
    const output = sanitizeBasic(
      '<p>a</p><script>alert(1)</script><style>p{display:none}</style><iframe src="https://example.com">fallback</iframe>'
        + '<object data="x">obj</object><embed src="x"><textarea>area</textarea><noscript>ns</noscript><template><p>tpl</p></template>',
    );
    expect(output).toBe('<p>a</p>');
  });

  it('removes SVG and MathML elements entirely', () => {
    const output = sanitizeBasic('<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg><math><mi>y</mi></math><p>ok</p>');
    expect(output).toBe('<p>ok</p>');
  });

  it('unwraps elements outside the allowlist and keeps their text', () => {
    expect(sanitizeBasic('<div><span>kept</span><img src="x" onerror="alert(1)"><button onclick="x()">press</button></div>')).toBe('keptpress');
  });

  it('allows tables only in the extended tag set', () => {
    const table = '<table><thead><tr><th>h</th></tr></thead><tbody><tr><td>c</td></tr></tbody></table><h5>five</h5><del>gone</del><hr>';
    const basic = sanitizeMarkdownHtml(table, BASIC_MARKDOWN_TAGS);
    expect(basic).not.toContain('<table');
    expect(basic).not.toContain('<h5');
    expect(basic).toContain('c');
    const extended = sanitizeMarkdownHtml(table, EXTENDED_MARKDOWN_TAGS);
    expect(extended).toContain('<table>');
    expect(extended).toContain('<td>c</td>');
    expect(extended).toContain('<h5>five</h5>');
    expect(extended).toContain('<del>gone</del>');
    expect(extended).toContain('<hr>');
  });

  it('is idempotent for hostile mixed input', () => {
    const hostile = '<p onclick="x()">a<script>b</script><a href="javascript:1">c</a><svg><p>d</p></svg><img src=x onerror=1></p><div>e</div>';
    const once = sanitizeMarkdownHtml(hostile, EXTENDED_MARKDOWN_TAGS);
    expect(sanitizeMarkdownHtml(once, EXTENDED_MARKDOWN_TAGS)).toBe(once);
  });

  it('handles empty and very long input', () => {
    expect(sanitizeBasic('')).toBe('');
    const long = `<p>${'a'.repeat(200000)}</p>`;
    expect(sanitizeBasic(long)).toBe(long);
  });
});

describe('externalLinkTarget', () => {
  it('accepts http and https, and mailto only when allowed', () => {
    expect(externalLinkTarget('https://example.com', { allowMailto: false })).toBe('https://example.com');
    expect(externalLinkTarget('HTTP://example.com', { allowMailto: false })).toBe('HTTP://example.com');
    expect(externalLinkTarget('mailto:a@example.com', { allowMailto: false })).toBeNull();
    expect(externalLinkTarget('mailto:a@example.com', { allowMailto: true })).toBe('mailto:a@example.com');
  });

  it('rejects missing, relative, and executable targets', () => {
    for (const href of [null, undefined, '', '/path', '#anchor', 'javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', 'https:example.com']) {
      expect(externalLinkTarget(href, { allowMailto: true })).toBeNull();
    }
  });
});

describe('normalizeMarkdownBullets', () => {
  it('rewrites only leading bullet glyphs followed by whitespace', () => {
    expect(normalizeMarkdownBullets('• one\n● two\nplain • not\n•nospace')).toBe('- one\n- two\nplain • not\n•nospace');
  });
});

describe('escapeHtmlText', () => {
  it('escapes all five HTML-significant characters', () => {
    expect(escapeHtmlText(`<a href="x" title='y'>&</a>`)).toBe('&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;');
  });
});

describe('DOMPurify option sets', () => {
  it('pin the exact forbidden lists each surface used before consolidation', () => {
    expect(CHAT_MARKDOWN_PURIFY_OPTIONS).toEqual({
      FORBID_TAGS: ['audio', 'iframe', 'img', 'source', 'style', 'video'],
      FORBID_ATTR: ['style'],
    });
    expect(ARTIFACT_MARKDOWN_PURIFY_OPTIONS).toEqual({
      FORBID_TAGS: ['audio', 'form', 'iframe', 'source', 'style', 'video'],
      FORBID_ATTR: ['style'],
    });
  });
});
