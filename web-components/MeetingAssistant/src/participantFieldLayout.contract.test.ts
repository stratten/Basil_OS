import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const refinementsCss = readFileSync('src/styles/meeting-assistant/refinements-responsive.css', 'utf8');

describe('Notetaker participant field layout', () => {
  it('stays out of the metadata grid stretch pass so WebKit re-measures its height when the column width changes', () => {
    const match = /(?:^|\n)\.meeting-participant-field\s*\{([^}]*)\}/.exec(refinementsCss);
    expect(match, 'missing .meeting-participant-field rule').not.toBeNull();
    const declarations = match![1];
    expect(declarations).toContain('align-self: start');
    expect(declarations).toContain('height: auto');
    expect(declarations).toContain('align-content: flex-start');
  });
});
