import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it, vi } from 'vitest';

let FilesDisplay: typeof import('./ResultAttachments').FilesDisplay;

beforeAll(async () => {
  vi.stubGlobal('window', {});
  FilesDisplay = (await import('./ResultAttachments')).FilesDisplay;
});

describe('FilesDisplay', () => {
  it('does not create attachments from result prose', () => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[]} resultText="File: /Users/example/unsafe-prose.txt" />
    );

    expect(markup).toBe('');
  });

  it('renders deleted files as non-clickable artifacts', () => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[{
        name: 'obsolete.txt',
        path: '/Users/example/obsolete.txt',
        operation: 'delete',
      }]} resultText="" />
    );

    expect(markup).toContain('Deleted: obsolete.txt');
    expect(markup).not.toContain('<button');
  });

  it('does not offer a preview for directories', () => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[{
        name: 'reports',
        path: '/Users/example/reports',
        kind: 'directory',
      }]} resultText="" />
    );

    expect(markup).toContain('Open /Users/example/reports');
    expect(markup).not.toContain('Preview /Users/example/reports');
    expect(markup).toContain('Open containing folder');
  });

  it.each([
    ['copy', 'Copied'],
    ['move', 'Moved'],
    ['rename', 'Renamed'],
  ])('shows %s source and destination paths', (operation, label) => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[{
        name: 'destination.txt',
        path: '/Users/example/destination.txt',
        sourcePath: '/Users/example/source.txt',
        operation,
      }]} resultText="" />
    );

    expect(markup).toContain(`${label}: /Users/example/source.txt → /Users/example/destination.txt`);
  });

  it('renders read files in a Retrieved sub-section with preview actions', () => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[{
        name: 'contract.pdf',
        path: '/Users/example/contract.pdf',
        operation: 'read',
      }]} resultText="" />
    );

    expect(markup).toContain('Retrieved');
    expect(markup).toContain('Retrieved: contract.pdf');
    expect(markup).toContain('<button');
    expect(markup).toContain('Open containing folder');
  });

  it('renders created files before the Retrieved sub-section', () => {
    const markup = renderToStaticMarkup(
      <FilesDisplay files={[
        {
          name: 'output.txt',
          path: '/Users/example/output.txt',
          operation: 'create',
        },
        {
          name: 'source.pdf',
          path: '/Users/example/source.pdf',
          operation: 'read',
        },
      ]} resultText="" />
    );

    const createdIndex = markup.indexOf('Created: output.txt');
    const retrievedHeaderIndex = markup.indexOf('Retrieved');
    const readIndex = markup.indexOf('Retrieved: source.pdf');

    expect(createdIndex).toBeGreaterThan(-1);
    expect(retrievedHeaderIndex).toBeGreaterThan(createdIndex);
    expect(readIndex).toBeGreaterThan(retrievedHeaderIndex);
  });

  describe('long file lists', () => {
    const createdFiles = (count: number) => Array.from({ length: count }, (_, index) => ({
      name: `file-${index}.txt`,
      path: `/Users/example/file-${index}.txt`,
      operation: 'create',
    }));
    const toggleText = (markup: string) => /class="basil-expandable-list__toggle"[^>]*>([^<]*)</.exec(markup)?.[1];

    it.each([3, 5])('offers no collapse for %i files', count => {
      const markup = renderToStaticMarkup(<FilesDisplay files={createdFiles(count)} resultText="" />);
      expect(toggleText(markup)).toBeUndefined();
    });

    it.each([6, 20])('offers to show all %i files, with every file still present for the expand', count => {
      const markup = renderToStaticMarkup(<FilesDisplay files={createdFiles(count)} resultText="" />);
      expect(toggleText(markup)).toBe(`Show all ${count} files`);
      expect(markup.match(/result-file-row"/g)).toHaveLength(count);
    });

    it('counts the Retrieved heading and read files in the same collapsible list, changed files first', () => {
      const markup = renderToStaticMarkup(
        <FilesDisplay
          files={[
            ...createdFiles(2),
            ...Array.from({ length: 6 }, (_, index) => ({ name: `ref-${index}.pdf`, path: `/Users/example/ref-${index}.pdf`, operation: 'read' })),
          ]}
          resultText=""
        />,
      );
      expect(toggleText(markup)).toBe('Show all 9 files');
      expect(markup.indexOf('Created: file-1.txt')).toBeLessThan(markup.indexOf('Retrieved</span>'));
      expect(markup).toContain('result-files__retrieved--after-changed');
    });
  });
});
