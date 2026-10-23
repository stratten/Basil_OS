import { describe, expect, it } from 'vitest';
import type { ThinkingSegment, TimelineEntry } from '../../types';
import {
  interactionAskerSpeaker,
  interactionResponseSpeaker,
  interactionSummary,
  interactionTranscriptCountdown,
  runControlStageClass,
  runControlTone,
  splitReasoningAroundInteractions,
  userInteractionsFromTimeline,
  type UserInteraction,
} from './userInteractions';

function interactionEntry(
  id: string,
  fields: Record<string, unknown>,
  timestamp = '2026-10-04T23:40:02+00:00',
): TimelineEntry {
  return {
    id: `user_interaction_${id}`,
    type: 'step',
    timestamp,
    content: String(fields.prompt ?? ''),
    detail_kind: 'user_interaction',
    metadata: {
      progress_step: 'Basil asked you a question',
      user_interaction: { interaction_id: id, asked_at: timestamp, ...fields },
    },
  };
}

const legacyQuestion: TimelineEntry = {
  id: 'dynamic_6f642bfa',
  type: 'step',
  timestamp: '2026-10-04T23:40:02.306478+00:00',
  content: 'Executing approved tool',
  detail_kind: 'tool_input',
  body: JSON.stringify({ prompt: 'I couldn\'t confirm "Le Fantasy".\\n\\nCould you double check?', input_type: 'text' }),
  metadata: { tool_name: 'request_user_input', raw_detail: true },
};

describe('response time limits', () => {
  const timeLimit = { deadline_at: '2026-10-04T23:42:00+00:00', limit_seconds: 120, on_timeout: 'continue_without' };

  it('reads the countdown of a waiting request and drops it once resolved', () => {
    const [waiting, answered] = userInteractionsFromTimeline([
      interactionEntry('cred', { kind: 'credential', status: 'waiting', prompt: 'Keychain access required', time_limit: timeLimit }),
      interactionEntry('done', { kind: 'credential', status: 'approved', prompt: 'Keychain access required', time_limit: timeLimit }, '2026-10-04T23:41:00+00:00'),
    ]);

    expect(waiting.timeLimit).toEqual({
      deadlineMs: Date.parse('2026-10-04T23:42:00+00:00'),
      limitSeconds: 120,
      onTimeout: 'continue_without',
    });
    expect(answered.timeLimit).toBeUndefined();
  });

  it('ignores a malformed countdown instead of rejecting the exchange', () => {
    const [interaction] = userInteractionsFromTimeline([
      interactionEntry('cred', { kind: 'credential', status: 'waiting', prompt: 'Keychain access required', time_limit: { limit_seconds: 'soon' } }),
    ]);

    expect(interaction.status).toBe('waiting');
    expect(interaction.timeLimit).toBeUndefined();
  });

  it('shows the transcript countdown only where no card already runs one', () => {
    const base = { status: 'waiting' as const, timeLimit: { deadlineMs: 1, limitSeconds: 60, onTimeout: 'deny' } };

    expect(interactionTranscriptCountdown({ ...base, kind: 'credential' })).toBe(base.timeLimit);
    expect(interactionTranscriptCountdown({ ...base, kind: 'approval' })).toBeUndefined();
    expect(interactionTranscriptCountdown({ ...base, kind: 'command_input' })).toBeUndefined();
    expect(interactionTranscriptCountdown({ ...base, kind: 'credential', status: 'timed_out' })).toBeUndefined();
    expect(interactionTranscriptCountdown({ kind: 'credential', status: 'waiting' })).toBeUndefined();
  });

  it('does not keep counting down for a request on a run that already ended', () => {
    const [interaction] = userInteractionsFromTimeline(
      [interactionEntry('cred', { kind: 'credential', status: 'waiting', prompt: 'Keychain access required', time_limit: timeLimit })],
      { runEnded: true },
    );

    expect(interaction.status).toBe('canceled');
    expect(interactionTranscriptCountdown(interaction)).toBeUndefined();
  });
});

describe('userInteractionsFromTimeline', () => {
  it('reads recorded exchanges in the order they were asked', () => {
    const interactions = userInteractionsFromTimeline([
      { id: 'step', type: 'step', timestamp: '2026-10-04T23:39:00+00:00', content: 'Searching' },
      interactionEntry('late', { kind: 'approval', status: 'approved', prompt: 'rm -rf build' }, '2026-10-04T23:50:00+00:00'),
      interactionEntry('early', {
        kind: 'clarification',
        status: 'answered',
        prompt: 'Which hotel?',
        response: 'La Fantaisie in the 9th',
        responded_at: '2026-10-04T23:44:00+00:00',
        options: ['La Fantaisie', 7],
      }),
    ]);

    expect(interactions.map(interaction => interaction.id)).toEqual(['early', 'late']);
    expect(interactions[0]).toMatchObject({
      entryId: 'user_interaction_early',
      kind: 'clarification',
      status: 'answered',
      response: 'La Fantaisie in the 9th',
      respondedAt: '2026-10-04T23:44:00+00:00',
      responseHidden: false,
      options: ['La Fantaisie'],
    });
  });

  it('ignores malformed exchange records', () => {
    expect(userInteractionsFromTimeline([
      interactionEntry('bad-kind', { kind: 'chat', status: 'answered', prompt: 'Hi' }),
      interactionEntry('bad-status', { kind: 'approval', status: 'maybe', prompt: 'Hi' }),
      { ...interactionEntry('no-record', {}), metadata: { user_interaction: 'oops' } },
    ])).toEqual([]);
  });

  it('falls back to the legacy clarification question without an answer', () => {
    const [interaction] = userInteractionsFromTimeline([legacyQuestion]);

    expect(interaction).toMatchObject({
      kind: 'clarification',
      status: 'unrecorded',
      prompt: 'I couldn\'t confirm "Le Fantasy".\n\nCould you double check?',
      askedAt: legacyQuestion.timestamp,
    });
  });

  it('prefers recorded exchanges over the legacy fallback so a question is never shown twice', () => {
    const interactions = userInteractionsFromTimeline([
      legacyQuestion,
      interactionEntry('cp', { kind: 'clarification', status: 'waiting', prompt: 'Which hotel?' }),
    ]);

    expect(interactions.map(interaction => interaction.id)).toEqual(['cp']);
  });

  it('skips legacy entries whose body is not parseable', () => {
    expect(userInteractionsFromTimeline([{ ...legacyQuestion, body: '{not json' }])).toEqual([]);
    expect(userInteractionsFromTimeline(undefined)).toEqual([]);
  });
});

describe('splitReasoningAroundInteractions', () => {
  const asked: UserInteraction = {
    id: 'cp',
    entryId: 'user_interaction_cp',
    kind: 'clarification',
    status: 'answered',
    prompt: 'Which hotel?',
    askedAt: '2026-10-04T23:40:02+00:00',
    responseHidden: false,
    options: [],
  };
  const segment = (iteration: number, recordedAt?: string): ThinkingSegment => ({
    iteration,
    text: `pass ${iteration}`,
    isComplete: true,
    ...(recordedAt ? { recordedAt } : {}),
  });

  it('places reasoning before and after the exchange it was interrupted by', () => {
    const blocks = splitReasoningAroundInteractions(
      [
        segment(1, '2026-10-04T23:39:00+00:00'),
        segment(2, '2026-10-04T23:40:01+00:00'),
        segment(3, '2026-10-04T23:45:00+00:00'),
      ],
      [asked],
    );

    expect(blocks.map(block => (block.type === 'reasoning'
      ? block.segments.map(item => item.iteration).join(',')
      : block.interaction.id))).toEqual(['1,2', 'cp', '3']);
  });

  it('compares local and UTC timestamps by instant', () => {
    const localBeforeAsk = new Date(Date.parse(asked.askedAt) - 1000);
    const pad = (value: number) => String(value).padStart(2, '0');
    const naiveLocal = `${localBeforeAsk.getFullYear()}-${pad(localBeforeAsk.getMonth() + 1)}-${pad(localBeforeAsk.getDate())}T${pad(localBeforeAsk.getHours())}:${pad(localBeforeAsk.getMinutes())}:${pad(localBeforeAsk.getSeconds())}`;
    const [first] = splitReasoningAroundInteractions([segment(1, naiveLocal)], [asked]);

    expect(first.type).toBe('reasoning');
  });

  it('puts undated reasoning after every exchange', () => {
    const blocks = splitReasoningAroundInteractions([segment(4), segment(9)], [asked]);

    expect(blocks.map(block => block.type)).toEqual(['interaction', 'reasoning']);
  });

  it('shows exchanges even with no reasoning at all', () => {
    expect(splitReasoningAroundInteractions([], [asked]).map(block => block.type)).toEqual(['interaction']);
  });
});

describe('interactionSummary', () => {
  const base: UserInteraction = {
    id: 'cp',
    entryId: 'user_interaction_cp',
    kind: 'clarification',
    status: 'answered',
    prompt: 'Which hotel did you mean?',
    askedAt: '2026-10-04T23:40:02+00:00',
    response: 'La Fantaisie',
    responseHidden: false,
    options: [],
  };

  it('pairs the question with the answer on separate lines', () => {
    expect(interactionSummary(base)).toBe('Basil asked: Which hotel did you mean?\nYou answered: La Fantaisie');
  });

  it('never reveals hidden answers and truncates long prompts', () => {
    const summary = interactionSummary({
      ...base,
      kind: 'command_input',
      prompt: `Password for ${'x'.repeat(200)}`,
      response: 'hunter2',
      responseHidden: true,
    });

    expect(summary).not.toContain('hunter2');
    expect(summary).toContain('You answered (hidden)');
    expect(summary.split('\n')[0].length).toBeLessThan(120);
  });

  it('describes a dismissed question', () => {
    expect(interactionSummary({ ...base, status: 'dismissed', response: undefined }))
      .toBe('Basil asked: Which hotel did you mean?\nYou closed this without answering');
  });

  it('names the option chosen for a provider permission', () => {
    expect(interactionSummary({ ...base, kind: 'provider_permission', status: 'approved', prompt: 'Run tests?', response: 'Allow always' }))
      .toBe('A provider asked permission: Run tests?\nYou approved: Allow always');
  });

  it('ignores response text on a canceled request', () => {
    expect(interactionSummary({ ...base, status: 'canceled', response: 'stale' }))
      .toBe('Basil asked: Which hotel did you mean?\nCanceled - the run ended before this was answered');
  });

  it('describes a note Basil read and a note it never got to', () => {
    const note: UserInteraction = { ...base, kind: 'guidance', prompt: 'Use the Paris office', response: undefined };
    expect(interactionSummary({ ...note, status: 'resolved' }))
      .toBe("You sent Basil a note: Use the Paris office\nBasil read it at its next step");
    expect(interactionSummary({ ...note, status: 'canceled' }))
      .toBe('You sent Basil a note: Use the Paris office\nNot delivered: the run finished first');
    expect(interactionSummary({ ...note, status: 'waiting' }))
      .toBe("You sent Basil a note: Use the Paris office\nWaiting for Basil's next step");
  });

  it('describes a pause while waiting, after resuming with a note, and when stopped', () => {
    const pause: UserInteraction = { ...base, kind: 'pause', prompt: 'Paused by you', response: undefined };
    expect(interactionSummary({ ...pause, status: 'waiting' }))
      .toBe('You paused the run: Paused by you\nPaused until you resume');
    expect(interactionSummary({ ...pause, status: 'resolved', response: 'Skip the PDF' }))
      .toBe('You paused the run: Paused by you\nYou resumed: Skip the PDF');
    expect(interactionSummary({ ...pause, status: 'canceled' }))
      .toBe('You paused the run: Paused by you\nStopped while paused');
  });

  it('describes a lost connection without claiming the user paused', () => {
    const lost: UserInteraction = { ...base, kind: 'connection_lost', prompt: 'Basil lost its connection', response: undefined };
    expect(interactionSummary({ ...lost, status: 'waiting' }))
      .toBe('Basil lost its connection: Basil lost its connection\nSaved and paused until you resume');
    expect(interactionSummary({ ...lost, status: 'resolved', response: 'Go ahead' }))
      .toBe('Basil lost its connection: Basil lost its connection\nYou resumed: Go ahead');
    expect(interactionSummary({ ...lost, status: 'canceled' }))
      .toBe('Basil lost its connection: Basil lost its connection\nStopped while interrupted');
    expect(interactionAskerSpeaker(lost)).toBe('app');
    expect(interactionResponseSpeaker({ ...lost, status: 'waiting' })).toBe('app');
    expect(interactionResponseSpeaker({ ...lost, status: 'resolved' })).toBe('user');
  });

  it('reads recorded notes and pauses from the timeline', () => {
    const interactions = userInteractionsFromTimeline([
      interactionEntry('note-1', { kind: 'guidance', status: 'resolved', prompt: 'Use the Paris office' }),
      interactionEntry('pause-1', { kind: 'pause', status: 'waiting', prompt: 'Paused by you' }, '2026-10-04T23:41:00+00:00'),
    ]);
    expect(interactions.map(interaction => [interaction.id, interaction.kind, interaction.status])).toEqual([
      ['note-1', 'guidance', 'resolved'],
      ['pause-1', 'pause', 'waiting'],
    ]);
  });

  it('presents a request still waiting on a run that has ended as canceled', () => {
    const timeline = [
      interactionEntry('ask-1', { kind: 'approval', status: 'waiting', prompt: 'sed -n 2p notes.txt' }),
      interactionEntry('ask-2', { kind: 'clarification', status: 'answered', prompt: 'Which file?', response: 'notes.txt' }, '2026-10-04T23:42:00+00:00'),
    ];
    expect(userInteractionsFromTimeline(timeline).map(interaction => interaction.status)).toEqual(['waiting', 'answered']);
    expect(userInteractionsFromTimeline(timeline, { runEnded: true }).map(interaction => interaction.status))
      .toEqual(['canceled', 'answered']);
    expect(userInteractionsFromTimeline(timeline, { runEnded: false }).map(interaction => interaction.status))
      .toEqual(['waiting', 'answered']);
  });
});

describe('interaction speakers', () => {
  const appInitiated = ['clarification', 'approval', 'credential', 'provider_target', 'command_input', 'provider_input', 'provider_permission'] as const;

  it.each(appInitiated)('starts a %s exchange with the app and answers it as the user', kind => {
    expect(interactionAskerSpeaker({ kind })).toBe('app');
    for (const status of ['waiting', 'answered', 'approved', 'denied', 'dismissed', 'timed_out', 'canceled'] as const) {
      expect(interactionResponseSpeaker({ kind, status })).toBe('user');
    }
  });

  it('starts a note with the user and always acknowledges it as the app', () => {
    expect(interactionAskerSpeaker({ kind: 'guidance' })).toBe('user');
    for (const status of ['waiting', 'resolved', 'canceled'] as const) {
      expect(interactionResponseSpeaker({ kind: 'guidance', status })).toBe('app');
    }
  });

  it('starts a pause with the user and treats only the resume as the user', () => {
    expect(interactionAskerSpeaker({ kind: 'pause' })).toBe('user');
    expect(interactionResponseSpeaker({ kind: 'pause', status: 'resolved' })).toBe('user');
    expect(interactionResponseSpeaker({ kind: 'pause', status: 'canceled' })).toBe('app');
    expect(interactionResponseSpeaker({ kind: 'pause', status: 'waiting' })).toBe('app');
  });
});

describe('run-control tone', () => {
  it('keeps pauses, queued notes, and lost connections off the amber Your turn color', () => {
    expect(runControlTone({ kind: 'pause' })).toBe('neutral');
    expect(runControlTone({ kind: 'guidance' })).toBe('neutral');
    expect(runControlTone({ kind: 'connection_lost' })).toBe('notice');
    expect(runControlTone({ kind: 'approval' })).toBeNull();
    expect(runControlTone({ kind: 'clarification' })).toBeNull();
    expect(runControlTone(undefined)).toBeNull();
  });

  it('adds a stage class only for a waiting run-control interaction', () => {
    expect(runControlStageClass({ kind: 'interaction', state: 'waiting', interaction: { kind: 'pause' } })).toBe(' is-run-control-neutral');
    expect(runControlStageClass({ kind: 'interaction', state: 'waiting', interaction: { kind: 'connection_lost' } })).toBe(' is-run-control-notice');
    expect(runControlStageClass({ kind: 'interaction', state: 'completed', interaction: { kind: 'pause' } })).toBe('');
    expect(runControlStageClass({ kind: 'interaction', state: 'waiting', interaction: { kind: 'approval' } })).toBe('');
    expect(runControlStageClass({ kind: 'phase', state: 'waiting' })).toBe('');
  });
});
