import { describe, expect, it } from 'vitest';
import { classifyArtifactFileType } from './artifactFileType';

const base = { preview: { capability: 'unknown' as const } };

describe('classifyArtifactFileType', () => {
  it.each([
    ['report.md', 'markdown'],
    ['index.HTML', 'html'],
    ['run.sh', 'shell'],
    ['network_monitor.applescript', 'shell'],
    ['Info.plist', 'config'],
    ['data.csv', 'data'],
    ['main.py', 'code'],
    ['notes.txt', 'text'],
    ['paper.pdf', 'pdf'],
    ['shot.png', 'image'],
    ['bundle.zip', 'archive'],
  ])('classifies %s as %s by extension', (displayName, category) => {
    expect(classifyArtifactFileType({ ...base, displayName }).category).toBe(category);
  });

  it('falls back to the path extension, then to the review kind, then to other', () => {
    expect(classifyArtifactFileType({ ...base, displayName: 'NetworkMonitor', localPath: '/tmp/a/run.sh' }).category).toBe('shell');
    expect(classifyArtifactFileType({
      ...base,
      displayName: 'NetworkMonitor',
      review: { revision: null, revisionCount: 0, kind: 'markdown', snapshotStatus: 'unavailable' },
    }).category).toBe('markdown');
    expect(classifyArtifactFileType({ ...base, displayName: 'NetworkMonitor' }).category).toBe('other');
  });

  it('treats dotfiles and trailing dots as having no extension', () => {
    expect(classifyArtifactFileType({ ...base, displayName: '.hidden' }).category).toBe('other');
    expect(classifyArtifactFileType({ ...base, displayName: 'name.' }).category).toBe('other');
  });

  it('gives each category a label and a distinct sort rank', () => {
    const md = classifyArtifactFileType({ ...base, displayName: 'a.md' });
    const sh = classifyArtifactFileType({ ...base, displayName: 'a.sh' });
    expect(md.label).toBe('Markdown');
    expect(md.sortRank).not.toBe(sh.sortRank);
  });
});
