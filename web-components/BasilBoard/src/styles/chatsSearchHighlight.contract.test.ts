import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Chats search highlight styling', () => {
  it('loads the shared search highlight rules on both entry points that use the transcript styles', () => {
    const messagesCss = readFileSync(resolve(__dirname, 'chats-messages.css'), 'utf8');
    expect(messagesCss.startsWith("@import '../../../shared/search/search-highlight.css';")).toBe(true);
    expect(readFileSync(resolve(__dirname, '../main.tsx'), 'utf8')).toContain("import './styles/chats-messages.css';");
    expect(readFileSync(resolve(__dirname, '../standalone/conversation-main.tsx'), 'utf8')).toContain("import '../styles/chats-messages.css';");
  });
});
