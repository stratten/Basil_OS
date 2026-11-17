import { describe, expect, it } from 'vitest';
import type { UserInteraction, UserInteractionStatus } from '../interaction/userInteractions';
import { foldRailStages, isQuietRailStage, isRailFold, MIN_RAIL_FOLD, railFoldTitle, type RailStage } from './railFold';

function phase(id: string, overrides: Partial<RailStage> = {}): RailStage {
  return { id, kind: 'phase', label: id, state: 'completed', startedAt: '2026-08-10T12:00:00Z', artifactCount: 0, ...overrides };
}

function exchange(id: string, status: UserInteractionStatus, kind: UserInteraction['kind'] = 'approval'): RailStage {
  const interaction = {
    id, entryId: id, kind, status, prompt: id, askedAt: '2026-08-10T12:00:00Z', responseHidden: false, options: [],
  } as UserInteraction;
  return { id, kind: 'interaction', label: 'Exchange', state: status === 'waiting' ? 'waiting' : 'completed', startedAt: '2026-08-10T12:00:00Z', artifactCount: 0, interaction };
}

const allSettled = (stages: RailStage[]) => new Set(stages.map(stage => stage.id));

describe('isQuietRailStage', () => {
  it('treats finished phases and ordinary finished exchanges as quiet', () => {
    expect(isQuietRailStage(phase('a'))).toBe(true);
    expect(isQuietRailStage(phase('a', { state: 'recorded' }))).toBe(true);
    for (const status of ['approved', 'answered', 'resolved', 'dismissed'] as const) {
      expect(isQuietRailStage(exchange('x', status))).toBe(true);
    }
  });

  it('never treats a failed, active, waiting, or document-carrying step as quiet', () => {
    expect(isQuietRailStage(phase('a', { state: 'failed' }))).toBe(false);
    expect(isQuietRailStage(phase('a', { state: 'active' }))).toBe(false);
    expect(isQuietRailStage(phase('a', { state: 'waiting' }))).toBe(false);
    expect(isQuietRailStage(phase('a', { artifactCount: 1 }))).toBe(false);
    expect(isQuietRailStage({ ...phase('o'), kind: 'outcome' })).toBe(false);
  });

  it('never treats a denied, timed out, canceled, waiting, or unrecorded exchange as quiet', () => {
    for (const status of ['denied', 'timed_out', 'canceled', 'waiting', 'unrecorded'] as const) {
      expect(isQuietRailStage(exchange('x', status))).toBe(false);
    }
  });

  it('never treats a pause, note, or lost connection as quiet, even once finished', () => {
    for (const kind of ['pause', 'guidance', 'connection_lost'] as const) {
      expect(isQuietRailStage(exchange('x', 'resolved', kind))).toBe(false);
    }
  });
});

describe('foldRailStages', () => {
  it('leaves a short stretch as separate chips', () => {
    const stages = [phase('a'), phase('b')];
    expect(stages.length).toBeLessThan(MIN_RAIL_FOLD);
    expect(foldRailStages(stages, allSettled(stages))).toEqual(stages);
  });

  it('folds a stretch of quiet steps into one chip with the step and exchange counts', () => {
    const stages = [phase('a'), exchange('b', 'approved'), phase('c'), exchange('d', 'answered'), phase('e')];
    const chips = foldRailStages(stages, allSettled(stages));
    expect(chips).toEqual([{ kind: 'fold', id: 'fold:a', count: 5, exchangeCount: 2 }]);
  });

  it('keeps the steps a reader scans for and folds the stretches between them', () => {
    const stages = [
      phase('a'), phase('b'), phase('c'),
      exchange('denied', 'denied'),
      phase('d'), phase('e'), phase('f'), phase('g'),
      phase('doc', { artifactCount: 1 }),
      phase('h'), phase('i'), phase('j'),
      { ...phase('outcome'), kind: 'outcome' as const },
    ];
    const chips = foldRailStages(stages, allSettled(stages));
    expect(chips.map(chip => (isRailFold(chip) ? `fold:${chip.count}` : chip.id))).toEqual(['fold:3', 'denied', 'fold:4', 'doc', 'fold:3', 'outcome']);
  });

  it('shows a step that has not settled as its own chip and folds it in once it settles', () => {
    const stages = [phase('a'), phase('b'), phase('c'), phase('d')];
    const beforeSettling = foldRailStages(stages, new Set(['a', 'b', 'c']));
    expect(beforeSettling.map(chip => chip.id)).toEqual(['fold:a', 'd']);
    expect(isRailFold(beforeSettling[0]) && beforeSettling[0].count).toBe(3);

    const afterSettling = foldRailStages(stages, allSettled(stages));
    expect(afterSettling).toEqual([{ kind: 'fold', id: 'fold:a', count: 4, exchangeCount: 0 }]);
  });

  it('keeps the same chip id as the stretch grows, so the chip is updated and not replaced', () => {
    const stages = [phase('a'), phase('b'), phase('c')];
    const first = foldRailStages(stages, allSettled(stages))[0];
    const grown = [...stages, phase('d'), phase('e')];
    const second = foldRailStages(grown, allSettled(grown))[0];
    expect(second.id).toBe(first.id);
  });

  it('does not fold a step until it is settled, so nothing folds on its own at arrival', () => {
    const stages = [phase('a'), phase('b'), phase('c')];
    expect(foldRailStages(stages, new Set())).toEqual(stages);
  });
});

describe('railFoldTitle', () => {
  it('says what the number counts and how it splits', () => {
    expect(railFoldTitle({ kind: 'fold', id: 'fold:a', count: 12, exchangeCount: 5 })).toBe('12 steps, all completed: 7 processing steps and 5 exchanges with you. Select the rail to see every step.');
  });

  it('uses the singular for one of either', () => {
    expect(railFoldTitle({ kind: 'fold', id: 'fold:a', count: 2, exchangeCount: 1 })).toBe('2 steps, all completed: 1 processing step and 1 exchange with you. Select the rail to see every step.');
  });
});
