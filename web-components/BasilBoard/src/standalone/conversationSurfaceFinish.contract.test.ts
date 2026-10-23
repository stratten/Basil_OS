import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('Conversation window surface finish', () => {
  const conversationEntry = readFileSync('src/standalone/conversation-main.tsx', 'utf8');
  const boardEntry = readFileSync('src/main.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/conversation-surface-finish.css', 'utf8');

  it('opts the standalone Conversation window into the background-only metallic finish without the board-only rules', () => {
    expect(conversationEntry).toContain("import '../styles/conversation-surface-finish.css';");
    expect(conversationEntry).toContain('enableBackdropSurfaceFinish();');
    expect(conversationEntry).not.toContain('basil-board-surface-finish.css');
  });

  it('shares the chats rules with the BasilBoard main window', () => {
    expect(boardEntry).toContain("import './styles/conversation-surface-finish.css';");
  });

  it('clears only the layout containers and header chrome, and only under the background-only finish', () => {
    expect(finishCss).toContain('html[data-surface-finish="metal_backdrop"] :is(');
    for (const container of ['.basil-board-detached-header', '.chats-tab', '.chats-sidebar', '.chats-tab > .chats-sidebar.chats-sidebar-collapsed', '.chats-sidebar-header', '.chats-main-header', '.chats-main', '.chats-message-viewport', '.chats-composer-region']) {
      expect(finishCss).toContain(container);
    }
    for (const solidSurface of ['.chats-message-bubble', '.chats-composer,', '.chats-composer\n']) {
      expect(finishCss).not.toContain(solidSurface);
    }
    expect(finishCss.match(/html\[data-surface-finish=/g)).toHaveLength(1);
  });
});
