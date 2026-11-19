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
    expect(markup).toContain('interaction-turn is-user is-answer');
    expect(markup).toContain('You answered');
    expect(markup).toContain('La Fantaisie in the 9th');
  });

  it('counts down a waiting request that has no card of its own, such as Keychain access', () => {
    const waitingCredential: UserInteraction = {
      ...answered,
      kind: 'credential',
      status: 'waiting',
      prompt: 'Keychain access required',
      response: undefined,
      respondedAt: undefined,
      timeLimit: { deadlineMs: Date.now() + 90_000, limitSeconds: 180, onTimeout: 'continue_without' },
    };

    const markup = renderToStaticMarkup(<InteractionExchange interaction={waitingCredential} />);

    expect(markup).toContain('response-countdown response-countdown--inline');
    expect(markup).toContain('Basil will carry on without it');
  });

  it('leaves the countdown to the approval card while an approval waits', () => {
    const waitingApproval: UserInteraction = {
      ...answered,
      kind: 'approval',
      status: 'waiting',
      prompt: 'git status',
      response: undefined,
      respondedAt: undefined,
      timeLimit: { deadlineMs: Date.now() + 90_000, limitSeconds: 120, onTimeout: 'deny' },
    };

    expect(renderToStaticMarkup(<InteractionExchange interaction={waitingApproval} />)).not.toContain('response-countdown');
  });

  it('exposes its timeline entry id as a navigation target', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={answered} />);

    expect(markup).toContain('data-interaction-entry-id="user_interaction_cp"');
  });

  it('shows a token-connect request and whether the service accepted it, never the token', () => {
    const connected = renderToStaticMarkup(
      <InteractionExchange
        interaction={{
          ...answered,
          kind: 'connection_token',
          status: 'approved',
          prompt: 'Connect Hugging Face at huggingface.co. Basil will send the token only to https://huggingface.co/mcp.',
          response: 'Hugging Face is connected. The service accepted the token (12 tools).',
        }}
      />,
    );
    expect(connected).toContain('Basil asked you to connect');
    expect(connected).toContain('huggingface.co');
    expect(connected).toContain('You connected');
    expect(connected).toContain('The service accepted the token (12 tools).');
    expect(connected).toContain('interaction-turn is-user is-answer');
    expect(connected).not.toContain('hf_');

    const failed = renderToStaticMarkup(
      <InteractionExchange
        interaction={{
          ...answered,
          kind: 'connection_token',
          status: 'resolved',
          prompt: 'Connect Hugging Face at huggingface.co.',
          response: 'The service rejected the token.',
        }}
      />,
    );
    expect(failed).toContain('The connection failed');
    expect(failed).toContain('The service rejected the token.');
    expect(failed).toContain('interaction-turn is-user is-negative');
  });

  it('shows an approval command as code rather than markdown', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'approval', status: 'denied', prompt: 'rm -rf **build**', response: undefined }} />,
    );

    expect(markup).toContain('<div class="interaction-exchange-command">rm -rf **build**</div>');
    expect(markup).not.toContain('basil-expandable-clamp');
    expect(markup).toContain('Basil asked to run');
    expect(markup).toContain('interaction-turn is-user is-negative');
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

describe('InteractionExchange speakers', () => {
  const note: UserInteraction = {
    ...answered,
    id: 'note',
    entryId: 'user_interaction_note',
    kind: 'guidance',
    status: 'resolved',
    prompt: 'Also include the `Spotlight` setting',
    response: undefined,
    respondedAt: '2026-10-04T23:44:00+00:00',
  };

  function speakers(markup: string): string[] {
    return Array.from(markup.matchAll(/data-speaker="(app|user)"/g)).map(match => match[1]);
  }

  it('puts the app first and you second when Basil asks and you answer', () => {
    expect(speakers(renderToStaticMarkup(<InteractionExchange interaction={answered} />))).toEqual(['app', 'user']);
    const approval = renderToStaticMarkup(
      <InteractionExchange interaction={{ ...answered, kind: 'approval', status: 'approved', prompt: 'ls', response: undefined }} />,
    );
    expect(speakers(approval)).toEqual(['app', 'user']);
    expect(approval.indexOf('interaction-exchange-command')).toBeLessThan(approval.indexOf('interaction-turn is-user'));
    expect(approval).toContain('interaction-turn is-app is-neutral');
  });

  it('shows a note you sent as your turn, then Basil acknowledging it as the app turn', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={note} />);

    expect(speakers(markup)).toEqual(['user', 'app']);
    expect(markup.indexOf('interaction-turn is-user')).toBeLessThan(markup.indexOf('interaction-turn is-app'));
    expect(markup).toContain('interaction-turn is-user is-neutral');
    expect(markup).toContain('interaction-turn is-app is-answer');
  });

  it('marks an undelivered or waiting note on the app turn', () => {
    const waiting = renderToStaticMarkup(<InteractionExchange interaction={{ ...note, status: 'waiting', respondedAt: undefined }} />);
    expect(waiting).toContain('interaction-turn is-app is-waiting');
    expect(waiting).toContain('interaction-exchange-waiting-dot');
    const canceled = renderToStaticMarkup(<InteractionExchange interaction={{ ...note, status: 'canceled' }} />);
    expect(canceled).toContain('interaction-turn is-app is-negative');
    expect(canceled).toContain('Not delivered: the run finished first');
  });

  it('shows a pause and its resume as two user turns, and a pause stopped by the run ending as user then app', () => {
    const pause: UserInteraction = { ...note, id: 'pause', entryId: 'user_interaction_pause', kind: 'pause', prompt: 'Paused at your request' };

    expect(speakers(renderToStaticMarkup(<InteractionExchange interaction={pause} />))).toEqual(['user', 'user']);
    const stopped = renderToStaticMarkup(<InteractionExchange interaction={{ ...pause, status: 'canceled' }} />);
    expect(speakers(stopped)).toEqual(['user', 'app']);
    expect(stopped).toContain('Stopped while paused');
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

describe('InteractionExchange approval card', () => {
  const longCommand = `osascript -e 'tell application "Mail" to make new outgoing message with properties {subject:"Hello there"}'\nsecond line`;
  const approval: UserInteraction = {
    id: 'ap',
    entryId: 'user_interaction_ap',
    kind: 'approval',
    status: 'approved',
    prompt: longCommand,
    askedAt: '2026-10-04T23:40:02+00:00',
    respondedAt: '2026-10-04T23:41:00+00:00',
    responseHidden: false,
    options: [],
    purpose: 'Creates a draft email in Mail so you can review it.',
  };

  it('leads with the agent explanation and keeps the command behind a Show command button', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={approval} />);

    expect(markup).toContain('What this does');
    expect(markup).toContain('Creates a draft email in Mail so you can review it.');
    expect(markup.indexOf('What this does')).toBeLessThan(markup.indexOf('interaction-exchange-command'));
    expect(markup).toContain('Show command');
    expect(markup).not.toContain('Show full command');
    expect(markup).not.toContain('basil-expandable-clamp');
  });

  it('offers the full script behind an expander and keeps its region closed until opened', () => {
    const markup = renderToStaticMarkup(
      <InteractionExchange
        interaction={{
          ...approval,
          scriptPath: '/tmp/run.scpt',
          scriptContent: 'tell application "Mail"\nactivate\nend tell',
        }}
      />,
    );

    expect(markup).toContain('View full script (3 lines)');
    expect(markup).toContain('/tmp/run.scpt');
    expect(markup).toMatch(/<div[^>]*basil-collapsible-region is-collapsed[^>]*aria-hidden="true"/);
    expect(markup).toContain('aria-expanded="false"');
  });

  it('credits the explanation to the agent, or to Basil when Basil wrote it', () => {
    const agents = renderToStaticMarkup(<InteractionExchange interaction={approval} />);
    const basils = renderToStaticMarkup(<InteractionExchange interaction={{ ...approval, purposeSource: 'basil' }} />);

    expect(agents).toContain('The agent&#x27;s explanation');
    expect(basils).toContain('Basil&#x27;s explanation');
    expect(basils).not.toContain('The agent&#x27;s explanation');
  });

  it('says so when the agent gave no explanation, and stays quiet for older records', () => {
    const missing = renderToStaticMarkup(<InteractionExchange interaction={{ ...approval, purpose: undefined, purposeMissing: true }} />);
    const older = renderToStaticMarkup(<InteractionExchange interaction={{ ...approval, purpose: undefined }} />);

    expect(missing).toContain('The agent did not explain this command.');
    expect(older).not.toContain('did not explain');
    expect(older).not.toContain('What this does');
    expect(older).toContain('Show command');
  });

  it('keeps even a short command behind the Show command button, collapsed, with no preview', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={{ ...approval, prompt: 'git status' }} />);

    expect(markup).toContain('Show command');
    expect(markup).toContain('basil-collapsible-region is-collapsed');
    expect(markup).toContain('<div class="interaction-exchange-command">git status</div>');
    expect(markup).not.toContain('basil-expandable-clamp');
  });
});

describe('InteractionExchange attached files', () => {
  const listing = "Attached for you to look at (local paths on the user's Mac):\n- /Users/me/Downloads/Meeting-2026-11-05-analysis.md\n- /Users/me/Projects/";
  const note: UserInteraction = {
    ...answered,
    kind: 'guidance',
    status: 'resolved',
    prompt: `I'm dropping the analysis here directly.\n\n${listing}`,
    response: undefined,
  };

  it('shows attached files as chips with the file name instead of a bulleted path list', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={note} />);

    expect(markup).toContain("I'm dropping the analysis here directly.");
    expect(markup).toContain('attachment-list__row-name');
    expect(markup).toContain('>Meeting-2026-11-05-analysis.md<');
    expect(markup).toContain('title="/Users/me/Downloads/Meeting-2026-11-05-analysis.md"');
    expect(markup).toContain('>Projects<');
    expect(markup).not.toContain('Attached for you to look at');
    expect(markup).not.toContain('<li>');
  });

  it('shows files attached to a resume note the same way', () => {
    const resumed: UserInteraction = { ...answered, kind: 'pause', status: 'resolved', response: `Carry on.\n\n${listing}` };
    const markup = renderToStaticMarkup(<InteractionExchange interaction={resumed} />);

    expect(markup).toContain('Carry on.');
    expect(markup).toContain('>Meeting-2026-11-05-analysis.md<');
    expect(markup).not.toContain('Attached for you to look at');
  });

  it('shows only the chips when the note had no text', () => {
    const markup = renderToStaticMarkup(<InteractionExchange interaction={{ ...note, prompt: listing }} />);

    expect(markup).toContain('>Meeting-2026-11-05-analysis.md<');
  });
});

describe('splitAttachedReferences', () => {
  it('leaves ordinary text, and a heading that is not a clean listing, untouched', async () => {
    const { splitAttachedReferences } = await import('./InteractionExchange');
    const heading = "Attached for you to look at (local paths on the user's Mac):";

    expect(splitAttachedReferences('Use the Paris office')).toEqual({ body: 'Use the Paris office', paths: [] });
    expect(splitAttachedReferences(`${heading}\nnot a bullet`)).toEqual({ body: `${heading}\nnot a bullet`, paths: [] });
    expect(splitAttachedReferences(`${heading}\n-`)).toEqual({ body: `${heading}\n-`, paths: [] });
    expect(splitAttachedReferences(`I wrote ${heading}\n- /a`)).toEqual({ body: `I wrote ${heading}\n- /a`, paths: [] });
  });

  it('keeps paths with spaces and special characters whole', async () => {
    const { splitAttachedReferences } = await import('./InteractionExchange');
    const heading = "Attached for you to look at (local paths on the user's Mac):";

    expect(splitAttachedReferences(`Hi\n\n${heading}\n- /Users/me/My Files/report (final) #2.pdf`)).toEqual({
      body: 'Hi',
      paths: ['/Users/me/My Files/report (final) #2.pdf'],
    });
  });
});
