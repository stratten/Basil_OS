// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { attachmentBasename, attachmentIsDirectory, mergeAttachmentPaths, pathEntries } from './attachmentPaths';

describe('attachmentPaths', () => {
  it('names a path by its last segment, ignoring trailing slashes', () => {
    expect(attachmentBasename('/Users/me/brief.pdf')).toBe('brief.pdf');
    expect(attachmentBasename('/Users/me/project/')).toBe('project');
    expect(attachmentBasename('/')).toBe('/');
  });

  it('treats an explicit flag as authoritative and falls back to the trailing slash', () => {
    expect(attachmentIsDirectory({ path: '/a/b/' })).toBe(true);
    expect(attachmentIsDirectory({ path: '/a/b' })).toBe(false);
    expect(attachmentIsDirectory({ path: '/a/b/', isDirectory: false })).toBe(false);
    expect(attachmentIsDirectory({ path: '/a/b', isDirectory: true })).toBe(true);
  });

  it('merges without duplicates or blanks and honors the limit', () => {
    expect(mergeAttachmentPaths(['/a'], ['/a', '/b', '', '  ', '/b', '/c'])).toEqual(['/a', '/b', '/c']);
    expect(mergeAttachmentPaths(['/a'], ['/b', '/c'], 2)).toEqual(['/a', '/b']);
  });

  it('gives duplicate paths distinct keys', () => {
    const keys = pathEntries(['/a', '/a']).map((entry) => entry.key);
    expect(new Set(keys).size).toBe(2);
  });
});
