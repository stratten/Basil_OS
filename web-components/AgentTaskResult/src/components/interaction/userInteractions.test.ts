import { describe, expect, it } from 'vitest';
import type { ThinkingSegment, TimelineEntry } from '../../types';
import {
  interactionSummary,
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
