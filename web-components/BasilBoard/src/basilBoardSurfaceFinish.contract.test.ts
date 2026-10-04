import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('BasilBoard main window surface finish', () => {
  const entry = readFileSync('src/main.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/basil-board-surface-finish.css', 'utf8');

  it('opts the window in and reuses the Conversation chats rules for its Chats tab', () => {
    expect(entry).toContain("import './styles/conversation-surface-finish.css';");
    expect(entry).toContain("import './styles/basil-board-surface-finish.css';");
    expect(entry).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears the Home and Todos layout containers only', () => {
    expect(finishCss).toContain(`${SCOPE} :is(`);
    for (const chrome of ['.home-view', '.home-transcript', '.home-composer', '.todo-view', '.todo-list-pane']) {
      expect(finishCss).toContain(chrome);
    }
    expect(finishCss.split(SCOPE).length - 1).toBe(1);
    for (const solidSurface of ['.home-message-assistant', '.home-composer-shell', '.todo-detail-pane', '.todo-workspace-pane']) {
      expect(finishCss).not.toContain(solidSurface);
    }
  });
});
