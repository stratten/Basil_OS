import { describe, expect, it } from 'vitest';
import { richTextToPlainText, sanitizeRichText } from './richTextSanitize';

describe('sanitizeRichText', () => {
  it('preserves the formatting tags emitted by RichTextComposer', () => {
    const result = sanitizeRichText('<p><strong>Plan</strong> <em>review</em><br><code>todo-1</code></p><ul><li>First</li></ul>');

    expect(result).toBe('<p><strong>Plan</strong> <em>review</em><br><code>todo-1</code></p><ul><li>First</li></ul>');
  });

  it('removes unexpected tags and every attribute while keeping user text', () => {
    const result = sanitizeRichText('<p class="unsafe"><a href="https://example.test">Review</a><img src="x" onerror="alert(1)"></p>');

    expect(result).toBe('<p>Review</p>');
    expect(result).not.toContain('href');
    expect(result).not.toContain('onerror');
  });

  it('returns an empty string for empty content and can extract readable text', () => {
    expect(sanitizeRichText('   ')).toBe('');
    expect(richTextToPlainText('<p>First <strong>second</strong></p>')).toBe('First second');
  });
});
