import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import { runControlTone, type UserInteractionStatus } from '../interaction/userInteractions';

export type RailStage = AgentRunOverviewPresentation['stages'][number];

/** One chip standing in for a stretch of uneventful steps. Its id comes from the first step it covers, so the chip keeps its identity as later steps join it and only its count changes. */
export interface RailFold {
  kind: 'fold';
  id: string;
  /** How many steps the chip covers. */
  count: number;
  /** How many of those steps were an exchange with the reader, such as an approval or a question. */
  exchangeCount: number;
}

export type RailChip = RailStage | RailFold;

/** A stretch shorter than this stays as separate chips, because a chip that covers two steps saves nothing. */
export const MIN_RAIL_FOLD = 3;

/** An exchange that ended the ordinary way. Denied, timed out, and canceled exchanges are what a reader scans for, so they never fold. */
const QUIET_EXCHANGE_STATUSES: ReadonlySet<UserInteractionStatus> = new Set(['approved', 'answered', 'resolved', 'dismissed']);

export function isRailFold(chip: RailChip): chip is RailFold {
  return chip.kind === 'fold';
}

/** A step that finished without anything for the reader to notice. Anything failed, waiting, in progress, carrying a document, ending the run, or running as a pause or note is never quiet. */
export function isQuietRailStage(stage: RailStage): boolean {
  if (stage.artifactCount > 0) return false;
  if (stage.kind === 'phase') return stage.state === 'completed' || stage.state === 'recorded';
  if (stage.kind === 'interaction') {
    const interaction = stage.interaction;
    return stage.state === 'completed'
      && interaction !== undefined
      && runControlTone(interaction) === null
      && QUIET_EXCHANGE_STATUSES.has(interaction.status);
  }
  return false;
}

/**
 * Folds each stretch of quiet steps into one chip. A quiet step joins a stretch only once its id is in `settledIds`: a step that has just arrived stays a chip of its own until the caller settles it, which is what lets the reader see each new step land before the count above it grows.
 */
export function foldRailStages(stages: readonly RailStage[], settledIds: ReadonlySet<string>): RailChip[] {
  const chips: RailChip[] = [];
  let stretch: RailStage[] = [];
  const closeStretch = () => {
    if (stretch.length >= MIN_RAIL_FOLD) {
      chips.push({
        kind: 'fold',
        id: `fold:${stretch[0].id}`,
        count: stretch.length,
        exchangeCount: stretch.filter(stage => stage.kind === 'interaction').length,
      });
    } else {
      chips.push(...stretch);
    }
    stretch = [];
  };
  for (const stage of stages) {
    if (isQuietRailStage(stage) && settledIds.has(stage.id)) {
      stretch.push(stage);
    } else {
      closeStretch();
      chips.push(stage);
    }
  }
  closeStretch();
  return chips;
}

/** The tooltip for a fold chip, which says what the number counts and how it splits. */
export function railFoldTitle(fold: RailFold): string {
  const exchanges = fold.exchangeCount === 1 ? '1 exchange' : `${fold.exchangeCount} exchanges`;
  const processing = fold.count - fold.exchangeCount;
  const steps = processing === 1 ? '1 processing step' : `${processing} processing steps`;
  return `${fold.count} steps, all completed: ${steps} and ${exchanges} with you. Select the rail to see every step.`;
}
