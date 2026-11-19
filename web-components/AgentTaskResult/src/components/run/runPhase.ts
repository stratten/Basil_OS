import type { RunPhase } from '../../../../shared/status/runPhase';
import type { ActivityStatusTone } from '../result/ExecutionTimeline';

// The phase reading is shared with the other windows that draw an agent task; import it from `shared/status/runPhase`.
export * from '../../../../shared/status/runPhase';

/** The one phase-to-tone mapping for run status dots and cards: the status card, and any list that shows a run beside its task. */
export function statusToneOfPhase(phase: RunPhase): ActivityStatusTone {
  switch (phase.kind) {
    case 'working':
    case 'verifying':
      return 'live';
    case 'awaiting':
      return 'attention';
    case 'paused':
      return 'paused';
    case 'canceled':
      return 'neutral';
    case 'settled':
      if (phase.outcome === 'partial') return 'partial';
      return phase.outcome === 'failed' ? 'danger' : 'success';
  }
}
