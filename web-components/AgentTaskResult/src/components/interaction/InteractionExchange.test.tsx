import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ThinkingSegment } from '../../types';
import { InteractionExchange, ReasoningWithInteractions } from './InteractionExchange';
import type { UserInteraction } from './userInteractions';

const answered: UserInteraction = {
  id: 'cp',
  entryId: 'user_interaction_cp',
  kind: 'clarification',
  status: 'answered',
  prompt: 'Which hotel did you mean?\n\n- **La Fantaisie**\n- Le Fantome',
  askedAt: '2026-10-04T23:40:02+00:00',
  response: 'La Fantaisie in the 9th',
  respondedAt: '2026-10-04T23:44:00+00:00',
  responseHidden: false,
  options: [],
};

const segments: ThinkingSegment[] = [
  { iteration: 1, text: 'Looking up the hotel', isComplete: true, recordedAt: '2026-10-04T23:39:00+00:00' },
  { iteration: 2, text: 'Searching shops nearby', isComplete: true, recordedAt: '2026-10-04T23:45:00+00:00' },
];

describe('InteractionExchange', () => {
  it('renders the question as markdown and the answer as the user reply', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={answered} />);

    expect(markup).toContain('class="interaction-exchange is-answered"');
    expect(markup).toContain('Basil asked');
    expect(markup).toContain('<strong>La Fantaisie</strong>');
    expect(markup).toContain('interaction-exchange-response is-answer');
    expect(markup).toContain('You answered');
    expect(markup).toContain('La Fantaisie in the 9th');
  });

  it('exposes its timeline entry id as a navigation target', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={answered} />);

    expect(markup).toContain('data-interaction-entry-id="user_interaction_cp"');
  });

  it('shows an approval command as code rather than markdown', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'approval', status: 'denied', prompt: 'rm -rf **build**', response: undefined }} />,
    );

    expect(markup).toContain('<pre class="interaction-exchange-command">rm -rf **build**</pre>');
    expect(markup).toContain('Basil asked to run');
    expect(markup).toContain('interaction-exchange-response is-negative');
    expect(markup).toContain('You declined');
  });

  it('shows the option chosen for a provider permission decision', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'provider_permission', status: 'denied', prompt: 'Run tests?', response: 'Reject always' }} />,
    );

    expect(markup).toContain('You declined');
    expect(markup).toContain('<div class="interaction-exchange-response-text">Reject always</div>');
  });

  it('shows submitted provider form values on separate lines', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'provider_input', response: 'Strategy: Balanced\nBranch: main' }} />,
    );

    expect(markup).toContain('Strategy: Balanced\nBranch: main');
  });

  it('marks a pending question as waiting', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, status: 'waiting', response: undefined, respondedAt: undefined }} />,
    );

    expect(markup).toContain('interaction-exchange-waiting-dot');
    expect(markup).toContain('Waiting for your answer');
  });

  it('does not repeat a waiting pause in the transcript, but keeps it once resolved', () => {
    const pause: UserInteraction = {
      ...answered,
      id: 'pause',
      entryId: 'user_interaction_pause',
      kind: 'pause',
      status: 'waiting',
      prompt: 'Paused at your request',
      response: undefined,
      respondedAt: undefined,
    };

    expect(renderToStaticMarkup(<InteractionExchange interaction={pause} />)).toBe('');
    const resolved = renderToStaticMarkup(<InteractionExchange interaction={{ ...pause, status: 'resolved' }} />);
    expect(resolved).toContain('You paused the run');
    expect(resolved).toContain('You resumed');
  });

  it('never renders a hidden answer', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'command_input', response: 'hunter2', responseHidden: true }} />,
    );

    expect(markup).not.toContain('hunter2');
    expect(markup).toContain('You answered (hidden)');
  });

  it('explains dismissed and unrecorded answers', () => {
    expect(renderToStaticMarkup(<InteractionExchange interaction={{ ...answered, status: 'dismissed', response: undefined }} />))
      .toContain('You closed this without answering');
    expect(renderToStaticMarkup(<InteractionExchange interaction={{ ...answered, status: 'unrecorded', response: undefined }} />))
      .toContain('Your answer was not recorded for this task');
  });
});

describe('ReasoningWithInteractions', () => {
  it('splits reasoning before and after the exchange', () => {
    const markup = renderToStaticMarkup(
      <ReasoningWithInteractions segments={segments} interactions={[answered]} isLive={false} collapseForResponse={false} />,
    );

    const firstReasoning = markup.indexOf('Looking up the hotel');
    const exchange = markup.indexOf('interaction-exchange');
    const laterReasoning = markup.indexOf('Searching shops nearby');
    expect(firstReasoning).toBeGreaterThan(-1);
    expect(exchange).toBeGreaterThan(firstReasoning);
    expect(laterReasoning).toBeGreaterThan(exchange);
  });

  it('renders plain reasoning unchanged when there were no exchanges', () => {
    const markup = renderToStaticMarkup(
      <ReasoningWithInteractions segments={segments} interactions={[]} isLive={false} collapseForResponse={false} />,
    );

    expect(markup).not.toContain('reasoning-with-interactions');
    expect(markup).toContain('2 reasoning passes');
  });
});
