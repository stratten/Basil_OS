import { beforeEach, describe, expect, it } from 'vitest';
import {
  discardComposerDraft,
  subscribeComposerDraftDiscarded,
  forgetComposerDraft,
  loadComposerDraft,
  moveComposerDraft,
  rememberComposerHtml,
  rememberComposerReferences,
  resetComposerDrafts,
} from './composerDraftStore';

describe('composerDraftStore', () => {
  beforeEach(() => resetComposerDrafts());

  it('has no draft for a task nobody has typed in', () => {
    expect(loadComposerDraft('follow-up', 'task-a')).toBeUndefined();
  });

  it('keeps each task its own draft', () => {
    rememberComposerHtml('follow-up', 'task-a', '<b>for A</b>', true);
    rememberComposerHtml('follow-up', 'task-b', 'for B', true);

    expect(loadComposerDraft('follow-up', 'task-a')?.html).toBe('<b>for A</b>');
    expect(loadComposerDraft('follow-up', 'task-b')?.html).toBe('for B');
  });

  it('keeps a follow-up and a note for the same task apart', () => {
    rememberComposerHtml('follow-up', 'task-a', 'a follow-up', true);
    rememberComposerHtml('note', 'task-a', 'a note', true);

    expect(loadComposerDraft('follow-up', 'task-a')?.html).toBe('a follow-up');
    expect(loadComposerDraft('note', 'task-a')?.html).toBe('a note');
  });

  it('does not treat empty markup as a draft', () => {
    rememberComposerHtml('follow-up', 'task-a', 'typed', true);
    rememberComposerHtml('follow-up', 'task-a', '<br>', false);

    expect(loadComposerDraft('follow-up', 'task-a')).toBeUndefined();
  });

  it('keeps attachments with the text and on their own', () => {
    rememberComposerHtml('follow-up', 'task-a', 'see these', true);
    rememberComposerReferences('follow-up', 'task-a', ['/tmp/one.txt', '/tmp/two.txt']);
    expect(loadComposerDraft('follow-up', 'task-a')).toEqual({ html: 'see these', referencePaths: ['/tmp/one.txt', '/tmp/two.txt'] });

    rememberComposerHtml('follow-up', 'task-a', '', false);
    expect(loadComposerDraft('follow-up', 'task-a')).toEqual({ html: '', referencePaths: ['/tmp/one.txt', '/tmp/two.txt'] });

    rememberComposerReferences('follow-up', 'task-a', []);
    expect(loadComposerDraft('follow-up', 'task-a')).toBeUndefined();
  });

  it('forgets a draft once it is sent', () => {
    rememberComposerHtml('note', 'task-a', 'sent', true);
    rememberComposerReferences('note', 'task-a', ['/tmp/one.txt']);

    forgetComposerDraft('note', 'task-a');

    expect(loadComposerDraft('note', 'task-a')).toBeUndefined();
  });

  it('returns a copy, so editing the result leaves the stored draft alone', () => {
    rememberComposerReferences('follow-up', 'task-a', ['/tmp/one.txt']);

    loadComposerDraft('follow-up', 'task-a')?.referencePaths.push('/tmp/changed.txt');

    expect(loadComposerDraft('follow-up', 'task-a')?.referencePaths).toEqual(['/tmp/one.txt']);
  });

  it('does not let a later change to the passed list change the stored draft', () => {
    const paths = ['/tmp/one.txt'];
    rememberComposerReferences('follow-up', 'task-a', paths);

    paths.push('/tmp/changed.txt');

    expect(loadComposerDraft('follow-up', 'task-a')?.referencePaths).toEqual(['/tmp/one.txt']);
  });

  it('moves a draft to a new key without leaving a copy behind', () => {
    rememberComposerHtml('follow-up', 'old-key', 'typed', true);

    moveComposerDraft('follow-up', 'old-key', 'new-key');

    expect(loadComposerDraft('follow-up', 'old-key')).toBeUndefined();
    expect(loadComposerDraft('follow-up', 'new-key')?.html).toBe('typed');
  });

  it('discards a draft and tells listeners which box it was, until they unsubscribe', () => {
    const heard: string[] = [];
    const unsubscribe = subscribeComposerDraftDiscarded((kind, key) => heard.push(`${kind}:${key}`));
    rememberComposerHtml('follow-up', 'task-a', 'typed', true);
    rememberComposerHtml('note', 'task-a', 'a note', true);

    discardComposerDraft('follow-up', 'task-a');

    expect(loadComposerDraft('follow-up', 'task-a')).toBeUndefined();
    expect(loadComposerDraft('note', 'task-a')?.html).toBe('a note');
    expect(heard).toEqual(['follow-up:task-a']);

    unsubscribe();
    discardComposerDraft('follow-up', 'task-a');
    expect(heard).toEqual(['follow-up:task-a']);
  });

  it('ignores a move of nothing, and a move to the same key', () => {
    moveComposerDraft('follow-up', 'missing', 'elsewhere');
    expect(loadComposerDraft('follow-up', 'elsewhere')).toBeUndefined();

    rememberComposerHtml('follow-up', 'same', 'typed', true);
    moveComposerDraft('follow-up', 'same', 'same');
    expect(loadComposerDraft('follow-up', 'same')?.html).toBe('typed');
  });
});
