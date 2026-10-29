import { describe, expect, it } from 'vitest';
import { diffLines, type DiffLine } from './diffLines';

function reconstructOld(diff: DiffLine[]): string[] {
  return diff.filter(line => line.type !== 'added').map(line => line.content);
}

function reconstructNew(diff: DiffLine[]): string[] {
  return diff.filter(line => line.type !== 'removed').map(line => line.content);
}

describe('diffLines', () => {
  it('returns an empty script for two empty texts', () => {
    expect(diffLines('', '')).toEqual([]);
  });

  it('marks every line unchanged for identical texts', () => {
    const diff = diffLines('a\nb\nc', 'a\nb\nc');
    expect(diff).toEqual([
      { type: 'unchanged', content: 'a', oldLineNumber: 1, newLineNumber: 1 },
      { type: 'unchanged', content: 'b', oldLineNumber: 2, newLineNumber: 2 },
      { type: 'unchanged', content: 'c', oldLineNumber: 3, newLineNumber: 3 },
    ]);
  });

  it('marks every line as added when the old text is empty', () => {
    const diff = diffLines('', 'a\nb');
    expect(diff).toEqual([
      { type: 'added', content: 'a', newLineNumber: 1 },
      { type: 'added', content: 'b', newLineNumber: 2 },
    ]);
  });

  it('marks every line as removed when the new text is empty', () => {
    const diff = diffLines('a\nb', '');
    expect(diff).toEqual([
      { type: 'removed', content: 'a', oldLineNumber: 1 },
      { type: 'removed', content: 'b', oldLineNumber: 2 },
    ]);
  });

  it('represents a pure single-line insertion with one added line', () => {
    const diff = diffLines('a\nc', 'a\nb\nc');
    expect(diff).toEqual([
      { type: 'unchanged', content: 'a', oldLineNumber: 1, newLineNumber: 1 },
      { type: 'added', content: 'b', newLineNumber: 2 },
      { type: 'unchanged', content: 'c', oldLineNumber: 2, newLineNumber: 3 },
    ]);
  });

  it('represents a pure single-line deletion with one removed line', () => {
    const diff = diffLines('a\nb\nc', 'a\nc');
    expect(diff).toEqual([
      { type: 'unchanged', content: 'a', oldLineNumber: 1, newLineNumber: 1 },
      { type: 'removed', content: 'b', oldLineNumber: 2 },
      { type: 'unchanged', content: 'c', oldLineNumber: 3, newLineNumber: 2 },
    ]);
  });

  it('reconstructs both original sequences for a modified middle line', () => {
    const oldLines = ['a', 'b', 'c'];
    const newLines = ['a', 'x', 'c'];
    const diff = diffLines(oldLines.join('\n'), newLines.join('\n'));

    expect(reconstructOld(diff)).toEqual(oldLines);
    expect(reconstructNew(diff)).toEqual(newLines);
    expect(diff.filter(line => line.type === 'removed')).toEqual([
      { type: 'removed', content: 'b', oldLineNumber: 2 },
    ]);
    expect(diff.filter(line => line.type === 'added')).toEqual([
      { type: 'added', content: 'x', newLineNumber: 2 },
    ]);
  });

  it('reconstructs both original sequences for a longer multi-edit document', () => {
    const oldLines = ['# Report', '', 'First finding.', 'Second finding.', 'Done.'];
    const newLines = ['# Report', '', 'First finding, revised.', 'Second finding.', 'Third finding.', 'Done.'];
    const diff = diffLines(oldLines.join('\n'), newLines.join('\n'));

    expect(reconstructOld(diff)).toEqual(oldLines);
    expect(reconstructNew(diff)).toEqual(newLines);
    expect(diff.some(line => line.type === 'added' && line.content === 'Third finding.')).toBe(true);
  });

  it('treats a single trailing blank line as significant', () => {
    const diff = diffLines('a', 'a\n');
    expect(reconstructNew(diff)).toEqual(['a', '']);
  });
});
