import { beforeEach, describe, expect, it } from 'vitest';
import {
  foldFollowUpComposerForRun,
  isFollowUpComposerCollapsed,
  resetFollowUpComposerViews,
  setFollowUpComposerCollapsed,
  unfoldFollowUpComposerAfterRun,
} from './followUpComposerViewStore';

beforeEach(() => {
  resetFollowUpComposerViews();
});

describe('the fold a run puts on the follow-up box', () => {
  it('folds an untouched chain when a run starts, and opens it again when the run finishes', () => {
    expect(foldFollowUpComposerForRun('root', 'turn-1')).toBe(true);
    expect(isFollowUpComposerCollapsed('root')).toBe(true);

    expect(unfoldFollowUpComposerAfterRun('root')).toBe(true);
    expect(isFollowUpComposerCollapsed('root')).toBe(false);
  });

  it('folds a turn only once, so a remount cannot undo the reader unfolding it', () => {
    foldFollowUpComposerForRun('root', 'turn-1');
    setFollowUpComposerCollapsed('root', false);

    expect(foldFollowUpComposerForRun('root', 'turn-1')).toBe(false);
    expect(isFollowUpComposerCollapsed('root')).toBe(false);
  });

  it('folds again for the next turn in the chain', () => {
    foldFollowUpComposerForRun('root', 'turn-1');
    unfoldFollowUpComposerAfterRun('root');

    expect(foldFollowUpComposerForRun('root', 'turn-2')).toBe(true);
    expect(isFollowUpComposerCollapsed('root')).toBe(true);
  });

  it('does not claim a box the reader had folded, so it stays folded when the run finishes', () => {
    setFollowUpComposerCollapsed('root', true);

    expect(foldFollowUpComposerForRun('root', 'turn-1')).toBe(false);
    expect(unfoldFollowUpComposerAfterRun('root')).toBe(false);
    expect(isFollowUpComposerCollapsed('root')).toBe(true);
  });

  it('gives the box up to the reader the moment they touch it, even if they fold it again', () => {
    foldFollowUpComposerForRun('root', 'turn-1');
    setFollowUpComposerCollapsed('root', false);
    setFollowUpComposerCollapsed('root', true);

    expect(unfoldFollowUpComposerAfterRun('root')).toBe(false);
    expect(isFollowUpComposerCollapsed('root')).toBe(true);
  });

  it('does nothing at the end of a run that never folded the box', () => {
    expect(unfoldFollowUpComposerAfterRun('root')).toBe(false);
    expect(isFollowUpComposerCollapsed('root')).toBe(false);
  });

  it('keeps chains separate', () => {
    foldFollowUpComposerForRun('root-a', 'turn-a');

    expect(isFollowUpComposerCollapsed('root-b')).toBe(false);
    expect(unfoldFollowUpComposerAfterRun('root-b')).toBe(false);
    expect(isFollowUpComposerCollapsed('root-a')).toBe(true);
  });

  it('forgets every claim on reset', () => {
    foldFollowUpComposerForRun('root', 'turn-1');
    resetFollowUpComposerViews();

    expect(isFollowUpComposerCollapsed('root')).toBe(false);
    expect(unfoldFollowUpComposerAfterRun('root')).toBe(false);
    expect(foldFollowUpComposerForRun('root', 'turn-1')).toBe(true);
  });
});
