// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ExecutionApprovalRequest } from '../../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const submitApprovalDecision = vi.fn();
const submitBrowserSensitiveFillApproval = vi.fn();
const submitProviderPermissionDecision = vi.fn();
const submitSettingsChangeApproval = vi.fn();

vi.mock('../../services/api', () => ({
  submitApprovalDecision,
  submitBrowserSensitiveFillApproval,
  submitProviderPermissionDecision,
  submitSettingsChangeApproval,
}));

vi.mock('../../store/agentStore', () => ({
  agentStore: {
    hideApproval: vi.fn(),
    removeApproval: vi.fn(),
    updateStatus: vi.fn(),
    updateProgressStep: vi.fn(),
    setError: vi.fn(),
    getActiveFollowUpId: vi.fn(),
  },
}));

let ApprovalOverlay: typeof import('./ApprovalOverlay').default;
let ApprovalSetOverlay: typeof import('./ApprovalSetOverlay').default;

beforeAll(async () => {
  ApprovalOverlay = (await import('./ApprovalOverlay')).default;
  ApprovalSetOverlay = (await import('./ApprovalSetOverlay')).default;
});

afterEach(() => {
  submitApprovalDecision.mockReset();
});

const shellApproval: ExecutionApprovalRequest = {
  approval_id: 'approval-shell',
  agent_task_id: 'task-1',
  command: 'ls -la',
  reason: 'Command not in whitelist',
  risk_level: 'low',
  execution_type: 'shell',
};

const providerApproval: ExecutionApprovalRequest = {
  approval_id: 'permission-1',
  agent_task_id: 'task-1',
  command: 'Run `rm -rf /tmp/scratch`?',
  reason: 'The provider wants to delete a scratch directory.',
  risk_level: 'medium',
  execution_type: 'provider_permission',
  provider_permission: {
    interaction_id: 'permission-1',
    provider_run_id: 'run-1',
    agent_task_id: 'task-1',
    subject: { type: 'command', command: 'rm -rf /tmp/scratch', cwd: '/tmp' },
    allow_option_id: 'allow-once',
    reject_option_id: 'reject-once',
  },
};

const providerApprovalWithoutAllow: ExecutionApprovalRequest = {
  ...providerApproval,
  provider_permission: {
    interaction_id: 'permission-1',
    provider_run_id: 'run-1',
    agent_task_id: 'task-1',
    subject: { type: 'command', command: 'rm -rf /tmp/scratch', cwd: '/tmp' },
    allow_option_id: null,
    reject_option_id: 'reject-once',
  },
};

describe('ApprovalOverlay provider permission presentation', () => {
  it('renders provider permission title, badge, and no remember checkbox', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={providerApproval} rememberChoice={false} />
    );

    expect(markup).toContain('Provider Permission Request');
    expect(markup).toContain('Provider');
    expect(markup).toContain('rm -rf /tmp/scratch');
    expect(markup).not.toContain('Remember this choice');
  });

  it('disables Approve when no allow option was offered', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay
        agentTaskId="task-1"
        approval={providerApprovalWithoutAllow}
        rememberChoice={false}
      />
    );

    expect(markup).toContain('decision-btn decision-btn--approve');
    expect(markup).toContain('disabled=""');
  });

  it('has no Cancel button, and Deny selects the provider reject option', async () => {
    submitProviderPermissionDecision.mockResolvedValue({ success: true, message: 'ok' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={providerApproval} rememberChoice={false} />);
    });

    const labels = Array.from(container.querySelectorAll('button')).map(button => button.textContent);
    expect(labels).toEqual(['Deny', 'Approve']);

    await act(async () => {
      Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Deny')?.click();
    });
    expect(submitProviderPermissionDecision).toHaveBeenCalledWith({
      agent_task_id: 'task-1',
      interaction_id: 'permission-1',
      selected_option_id: 'reject-once',
    });
    act(() => root.unmount());
  });
});

describe('ApprovalOverlay existing approval types', () => {
  it('keeps shell approval presentation unchanged', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={shellApproval} rememberChoice={false} />
    );

    expect(markup).toContain('Command Approval Required');
    expect(markup).toContain('Remember this choice');
    expect(markup).not.toContain('Provider Permission Request');
  });

  it('counts down to the timeout when the approval has a time limit, and not otherwise', () => {
    const timed = renderToStaticMarkup(
      <ApprovalOverlay
        agentTaskId="task-1"
        approval={{ ...shellApproval, time_limit: { deadlineMs: Date.now() + 90_000, limitSeconds: 120, onTimeout: 'deny_and_retry' } }}
        rememberChoice={false}
      />
    );
    const untimed = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={shellApproval} rememberChoice={false} />
    );

    expect(timed).toContain('response-countdown response-countdown--card');
    expect(timed).toContain('decline this and try another approach');
    expect(untimed).not.toContain('response-countdown');
  });

  it('submits the approval owner turn instead of the root display task', async () => {
    submitApprovalDecision.mockResolvedValue({ success: true, message: 'approved' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ApprovalOverlay
          agentTaskId="root-task"
          approval={{ ...shellApproval, agent_task_id: 'child-turn' }}
          rememberChoice={false}
        />,
      );
    });

    const approveButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Approve');
    await act(async () => {
      approveButton?.click();
    });

    expect(submitApprovalDecision).toHaveBeenCalledWith(expect.objectContaining({
      approval_id: 'approval-shell',
      agent_task_id: 'child-turn',
    }));
    act(() => root.unmount());
  });

  it('renders every approval in a simultaneous approval set', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[
          shellApproval,
          { ...shellApproval, approval_id: 'approval-shell-2', command: 'mdfind Calls_Meetings' },
        ]}
        rememberChoice={false}
      />,
    );

    expect(markup).toContain('2 Command Approvals Required');
    expect(markup).toContain('ls -la');
    expect(markup).toContain('mdfind Calls_Meetings');
  });
});

describe('ApprovalSetOverlay single-approval rendering (regression)', () => {
  it('renders exactly one "Command Approval Required" occurrence and no aggregate wrapper card', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[shellApproval]}
        rememberChoice={false}
      />,
    );

    const titleOccurrences = markup.split('Command Approval Required').length - 1;
    expect(titleOccurrences).toBe(1);
    // The single-approval path renders ApprovalOverlay directly (embedded
    // is left at its default false), so the inert approval-set-card
    // wrapper class -- only meaningful for the multi-approval stack --
    // should never appear, and there should be exactly one overlay-backdrop
    // (not one from ApprovalSetOverlay nested around another from
    // ApprovalOverlay).
    expect(markup).not.toContain('approval-set-card');
    expect(markup.match(/overlay-backdrop/g)?.length).toBe(1);
  });

  it('does not repeat the shell-command title for each embedded item in a simultaneous approval set', () => {
    const markup = renderToStaticMarkup(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={[
          shellApproval,
          { ...shellApproval, approval_id: 'approval-shell-2', command: 'mdfind Calls_Meetings' },
        ]}
        rememberChoice={false}
      />,
    );

    expect(markup).toContain('2 Command Approvals Required');
    // The literal singular heading would only appear if an embedded item
    // redundantly repeated it; the aggregate header uses the plural form.
    expect(markup).not.toContain('Command Approval Required');
    expect(markup).toContain('approval-set-card');
  });
});

describe('ApprovalOverlay agent explanation and remember eligibility', () => {
  const explained: ExecutionApprovalRequest = {
    ...shellApproval,
    command: 'bash /tmp/report.sh',
    purpose: 'Builds the weekly report from the exported CSV.',
    whitelist: {
      eligible: false,
      reason: 'A bare bash would allow any command or script, so Basil asks every time.',
      advice: { recommend: false, reason: 'It is a script.', downgraded: false },
    },
    script_content: 'echo report\n',
    script_path: '/tmp/report.sh',
  };

  const render = (approval: ExecutionApprovalRequest) =>
    renderToStaticMarkup(<ApprovalOverlay agentTaskId="task-1" approval={approval} rememberChoice={false} />);

  it("shows the agent's explanation and the script path beside the script toggle, with no recommendation for a choice that cannot be remembered", () => {
    const markup = render(explained);

    expect(markup).toContain('What this does');
    expect(markup).toContain('Builds the weekly report from the exported CSV.');
    expect(markup).toContain('The agent&#x27;s explanation');
    expect(markup).not.toContain('recommends');
    expect(markup).not.toContain('Ask me each time');
    expect(markup).not.toContain('It is a script.');
    expect(markup).toContain('View full script (2 lines)');
    expect(markup).toContain('/tmp/report.sh');
  });

  it('hides the remember checkbox and says why when the command can never be remembered', () => {
    const markup = render(explained);

    expect(markup).not.toContain('Remember this choice');
    expect(markup).toContain('A bare bash would allow any command or script');
    expect(markup).not.toContain('This approval applies to this run only.');
  });

  it('says it once, in one place, when the command cannot be remembered, and keeps the plain statement for a backend that sent no reason', () => {
    const once = render({
      ...explained,
      whitelist: {
        eligible: false,
        reason: 'python can run any code, so Basil asks every time instead of remembering it.',
        advice: { recommend: false, reason: 'python can run any code, so Basil asks every time instead of remembering it.', downgraded: true },
      },
    });

    expect(once.match(/python can run any code/g)?.length).toBe(1);
    expect(once).not.toContain('overrode');
    expect(once).not.toContain('recommends');
    expect(once.indexOf('approval-remember-blocked')).toBeGreaterThan(once.indexOf('What this does'));

    const bare = render({ ...explained, whitelist: { eligible: false, reason: '', advice: null } });
    expect(bare).toContain('This approval applies to this run only.');
  });

  it('credits the explanation to the agent, or to Basil when Basil wrote it', () => {
    const agents = render({ ...shellApproval, purpose: 'Lists the folder.' });
    const agentsExplicitly = render({ ...shellApproval, purpose: 'Lists the folder.', purpose_source: 'agent' });
    const basils = render({ ...shellApproval, purpose: 'Connect Example at https://mcp.example.com/mcp.', purpose_source: 'basil' });

    expect(agents).toContain('The agent&#x27;s explanation');
    expect(agentsExplicitly).toContain('The agent&#x27;s explanation');
    expect(basils).toContain('Basil&#x27;s explanation');
    expect(basils).not.toContain('The agent&#x27;s explanation');
    expect(basils).toContain('Connect Example at https://mcp.example.com/mcp.');
  });

  it('recommends remembering only when the agent says yes and the command is eligible', () => {
    const markup = render({
      ...shellApproval,
      purpose: 'Lists the folder.',
      whitelist: { eligible: true, reason: '', advice: { recommend: true, reason: 'Read-only and narrow.', downgraded: false } },
    });

    expect(markup).toContain('Remember this choice');
    expect(markup).toContain('The agent recommends remembering this: Read-only and narrow.');
    expect(markup).not.toContain('This approval applies to this run only.');
    // The advice sits with the checkbox it is about, and not in the box that explains the command.
    expect(markup.indexOf('The agent recommends')).toBeGreaterThan(markup.indexOf('Remember this choice'));
    expect(markup.indexOf('The agent recommends')).toBeGreaterThan(markup.indexOf('approval-explanation__source'));
  });

  it('says so when the agent advises asking each time about a command that could be remembered', () => {
    const markup = render({
      ...shellApproval,
      purpose: 'Lists the folder.',
      whitelist: { eligible: true, reason: '', advice: { recommend: false, reason: 'The folder changes often.', downgraded: false } },
    });

    expect(markup).toContain('The agent recommends asking each time: The folder changes often.');
    expect(markup).toContain('Remember this choice');
  });

  it('says exactly which commands remembering would approve, in the primary text, when a pattern arrives', () => {
    const markup = render({
      ...shellApproval,
      command: 'gh gist view 8edb73ec --files',
      generalized_pattern: 'gh gist view',
      purpose: 'Lists the files in the gist.',
      whitelist: {
        eligible: true,
        reason: '',
        advice: { recommend: true, reason: 'Read-only.', downgraded: false },
        pattern: 'gh gist view',
        broad: false,
      },
    });

    expect(markup).toContain('If remembered, Basil will approve any command that starts with');
    expect(markup).toContain('<code class="approval-pattern__words">gh gist view</code>');
    expect(markup).not.toContain('Pattern: ');
    expect(markup).not.toContain('approval-pattern-broad');
  });

  it('warns when remembering would approve every use of a tool, and names the tool', () => {
    const markup = render({
      ...shellApproval,
      command: 'ls -la /tmp',
      generalized_pattern: 'ls',
      whitelist: { eligible: true, reason: '', advice: null, pattern: 'ls', broad: true },
    });

    expect(markup).toContain('approval-pattern-broad');
    expect(markup).toContain('would approve every');
    expect(markup).toContain('<code class="approval-pattern__words">ls</code>');
  });

  it('shows neither the pattern nor the warning when the approval cannot be remembered', () => {
    const markup = render({
      ...shellApproval,
      generalized_pattern: 'gh',
      whitelist: { eligible: false, reason: 'Remembering only gh would approve every gh command.', advice: null, pattern: 'gh', broad: false },
    });

    expect(markup).not.toContain('If remembered');
    expect(markup).not.toContain('approval-pattern-broad');
    expect(markup).toContain('Remembering only gh would approve every gh command.');
  });

  const connectedToolApproval = (toolName: string, destructive: boolean): ExecutionApprovalRequest => ({
    ...shellApproval,
    command: `mcp:Gmail:${toolName}({"messageId":"AAA"})`,
    generalized_pattern: `mcp:Gmail:${toolName}({messageId:AAA})`,
    reason: 'This tool is set to ask before it runs',
    purpose: 'Does one thing to one message.',
    whitelist: {
      eligible: true,
      reason: '',
      advice: null,
      pattern: '',
      broad: false,
      tool_policy: { connection_id: 'conn-gmail', connection_name: 'Gmail', tool_name: toolName, destructive },
    },
  });

  it('offers a connected tool as always allow for that one tool, with no command pattern and no cautions until it is ticked', () => {
    const markup = render(connectedToolApproval('label_message', false));

    expect(markup).toContain('Always allow label_message on Gmail');
    expect(markup).not.toContain('Remember this choice');
    expect(markup).not.toContain('Pattern: ');
    expect(markup).not.toContain('If remembered');
    expect(markup).not.toContain('approval-tool-destructive');
    expect(markup).not.toContain('This changes only this tool');
    expect(markup).not.toContain('This tool deletes or sends things.');
  });

  it('does not repeat that a connected tool is set to ask first, since that is why the card is showing', () => {
    const markup = render(connectedToolApproval('label_message', false));

    expect(markup).not.toContain('set to ask before it runs');
    expect(markup).not.toContain('approval-reason');
  });

  it('still shows the reason on a shell approval', () => {
    const markup = render(shellApproval);

    expect(markup).toContain('approval-reason');
    expect(markup).toContain('Command not in whitelist');
  });

  async function mountApproval(approval: ExecutionApprovalRequest) {
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={approval} rememberChoice={false} />);
    });
    const checkbox = container.querySelector<HTMLInputElement>('.approval-remember input[type="checkbox"]');
    const toggle = async () => {
      await act(async () => {
        checkbox?.click();
      });
    };
    return { container, checkbox, toggle, unmount: () => act(() => root.unmount()) };
  }

  it('shows one caution under the checkbox only while Always allow is ticked, saying it covers only this tool and can be undone', async () => {
    const view = await mountApproval(connectedToolApproval('label_message', false));
    expect(view.checkbox).not.toBeNull();
    expect(view.container.querySelector('.approval-remember ~ [role="note"]')).toBeNull();

    await view.toggle();
    const notes = view.container.querySelectorAll('.approval-remember ~ [role="note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toContain('Basil will run label_message without asking again.');
    expect(notes[0].textContent).toContain('This changes only this tool, and you can undo it in Settings → Connections.');
    expect(notes[0].textContent).not.toContain('deletes or sends');
    expect(notes[0].className).not.toContain('approval-tool-destructive');

    await view.toggle();
    expect(view.container.querySelector('.approval-remember ~ [role="note"]')).toBeNull();
    view.unmount();
  });

  it('adds the deletes-or-sends warning to that same caution for a destructive connected tool, and only once ticked', async () => {
    const view = await mountApproval(connectedToolApproval('send_draft', true));
    expect(view.container.querySelector('.approval-tool-destructive')).toBeNull();
    expect(view.container.textContent).not.toContain('This tool deletes or sends things.');

    await view.toggle();
    const notes = view.container.querySelectorAll('.approval-remember ~ [role="note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].className).toContain('approval-tool-destructive');
    expect(notes[0].textContent).toContain('This tool deletes or sends things.');
    expect(notes[0].textContent).toContain('Basil will run send_draft without asking again.');
    expect(notes[0].textContent).toContain('This changes only this tool, and you can undo it in Settings → Connections.');
    expect(notes[0].querySelector('code.approval-pattern__words')?.textContent).toBe('send_draft');
    view.unmount();
  });

  it('names no connection when the backend sent none', () => {
    const markup = render({
      ...shellApproval,
      whitelist: {
        eligible: true,
        reason: '',
        advice: null,
        tool_policy: { connection_id: 'conn-1', connection_name: '', tool_name: 'create_request', destructive: false },
      },
    });

    expect(markup).toContain('Always allow create_request');
    expect(markup).not.toContain(' on </');
  });

  it('falls back to the old pattern line when the backend sends no pattern with the whitelist status', () => {
    const markup = render({ ...shellApproval, generalized_pattern: 'ls', whitelist: { eligible: true, reason: '', advice: null } });

    expect(markup).toContain('Pattern: ls');
    expect(markup).not.toContain('If remembered');
  });

  it('flags a missing explanation and shows no advice', () => {
    const markup = render({
      ...shellApproval,
      purpose_missing: true,
      whitelist: { eligible: true, reason: '', advice: null },
    });

    expect(markup).toContain('The agent did not explain this command.');
    expect(markup).not.toContain('The agent recommends');
    expect(markup).not.toContain('What this does');
  });

  it('shows the script path and a notice when the script text is withheld', () => {
    const markup = render({
      ...shellApproval,
      script_path: '/tmp/huge.sh',
      script_notice: 'This script is larger than 256 KB, so its text is not shown.',
    });

    expect(markup).toContain('/tmp/huge.sh');
    expect(markup).toContain('larger than 256 KB');
    expect(markup).not.toContain('View full script');
  });

  it('keeps the previous card when the backend sends no explanation fields', () => {
    const markup = render(shellApproval);

    expect(markup).toContain('Remember this choice');
    expect(markup).not.toContain('What this does');
    expect(markup).not.toContain('The agent did not explain');
  });

  it('never submits a remember choice for an approval that cannot be remembered', async () => {
    submitApprovalDecision.mockResolvedValue({ success: true, message: 'approved' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={explained} rememberChoice={true} />);
    });

    const approveButton = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Approve');
    await act(async () => {
      approveButton?.click();
    });

    expect(submitApprovalDecision).toHaveBeenCalledWith(expect.objectContaining({ approval_id: 'approval-shell', remember_choice: false }));
    act(() => root.unmount());
  });
});

describe('ApprovalOverlay compact command presentation', () => {
  const longCommand = `osascript get-inbox-subjects ${'x'.repeat(200)}`;
  const withPurpose: ExecutionApprovalRequest = { ...shellApproval, command: longCommand, purpose: 'Lists the subjects in your inbox.' };
  const render = (approval: ExecutionApprovalRequest) =>
    renderToStaticMarkup(<ApprovalOverlay agentTaskId="task-1" approval={approval} rememberChoice={false} />);

  it('leads with the explanation and clamps a long command to its first line behind an expander', () => {
    const markup = render(withPurpose);

    expect(markup.indexOf('Lists the subjects in your inbox.')).toBeLessThan(markup.indexOf('osascript get-inbox'));
    expect(markup).toContain('Show full command');
    expect(markup).toContain('basil-expandable-clamp__content is-clamped');
  });

  it('shows a short command in full with no expander', () => {
    const markup = render({ ...shellApproval, purpose: 'Lists the folder.' });

    expect(markup).toContain('ls -la');
    expect(markup).not.toContain('Show full command');
    expect(markup).not.toContain('…');
  });

  it('clamps a multi-line command to its first line and lifts the clamp on expand, without swapping the text', async () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const multiLine = 'echo one\necho two\necho three';
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={{ ...shellApproval, command: multiLine, purpose: 'Echoes.' }} rememberChoice={false} />);
    });

    const commandContent = () => container.querySelector('.command-display .basil-expandable-clamp__content');
    // The whole command stays in the page so the height can animate; only the clamp hides the rest.
    expect(commandContent()?.textContent).toBe(multiLine);
    expect(commandContent()?.classList.contains('is-clamped')).toBe(true);
    const toggle = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Show full command');
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    await act(async () => {
      toggle?.click();
    });
    expect(commandContent()?.textContent).toBe(multiLine);
    expect(commandContent()?.classList.contains('is-clamped')).toBe(false);
    expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Hide full command')).toBe(true);
    act(() => root.unmount());
  });

  it('still warns prominently, above the command, when the agent gave no explanation', () => {
    const markup = render({ ...shellApproval, command: longCommand, purpose_missing: true });

    expect(markup.indexOf('The agent did not explain this command.')).toBeLessThan(markup.indexOf('osascript get-inbox'));
  });

  it('keeps Approve, Deny and the dangerous-change warning, with no duplicate Cancel', () => {
    const markup = render({ ...withPurpose, risk_level: 'high' });

    expect(markup).toContain('Approve');
    expect(markup).toContain('Deny');
    expect(markup).not.toContain('>Cancel<');
    expect(markup).toContain('This command may cause permanent changes');
  });
});

describe('ApprovalOverlay title row and command box', () => {
  const render = (approval: ExecutionApprovalRequest, embedded = false) =>
    renderToStaticMarkup(<ApprovalOverlay agentTaskId="task-1" approval={{ ...approval, purpose: 'Lists the folder.' }} rememberChoice={false} embedded={embedded} />);

  it('puts the risk badge at the right of the title row, with nothing else in the first body row', () => {
    const markup = render(shellApproval);

    const titleRow = markup.slice(markup.indexOf('overlay-title'), markup.indexOf('overlay-body'));
    expect(titleRow).toContain('Command Approval Required');
    expect(titleRow).toContain('risk-badge low');
    expect(titleRow.indexOf('Command Approval Required')).toBeLessThan(titleRow.indexOf('risk-badge'));
    const body = markup.slice(markup.indexOf('overlay-body'));
    expect(body).not.toContain('risk-badge');
    expect(body.startsWith('overlay-body"><div class="approval-section approval-explanation"')).toBe(true);
  });

  it('keeps the risk badge in the card body for a card in a stack, which has no title row', () => {
    const markup = render(shellApproval, true);

    expect(markup).not.toContain('overlay-title');
    expect(markup).toContain('risk-badge low');
  });

  it('keeps the kind tag in the body, away from the badge, for an AppleScript approval', () => {
    const markup = render({ ...shellApproval, execution_type: 'applescript' });

    const titleRow = markup.slice(markup.indexOf('overlay-title'), markup.indexOf('overlay-body'));
    expect(titleRow).toContain('AppleScript Approval Required');
    expect(titleRow).toContain('risk-badge');
    expect(titleRow).not.toContain('approval-tag');
    expect(markup.slice(markup.indexOf('overlay-body'))).toContain('<span class="approval-tag">AppleScript</span>');
  });

  it('marks the command box so it takes the history card color, and leaves other command boxes alone', () => {
    const markup = render(shellApproval);

    expect(markup).toContain('class="command-display approval-command-display"');
  });
});

describe('ApprovalOverlay decision note', () => {
  async function renderShellApproval(): Promise<{ container: HTMLDivElement; unmount: () => void }> {
    submitApprovalDecision.mockResolvedValue({ success: true, message: 'ok' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={shellApproval} rememberChoice={false} />);
    });
    return { container, unmount: () => act(() => root.unmount()) };
  }

  async function typeNote(container: HTMLElement, text: string): Promise<void> {
    const toggle = container.querySelector<HTMLButtonElement>('.approval-note-toggle');
    if (toggle?.getAttribute('aria-expanded') === 'false') {
      await act(async () => {
        toggle.click();
      });
    }
    const textarea = container.querySelector('textarea.approval-note-input') as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    await act(async () => {
      setter?.call(textarea, text);
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  async function press(container: HTMLElement, label: string): Promise<void> {
    const button = Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent === label);
    await act(async () => {
      button?.click();
    });
  }

  it('sends the trimmed note with a denial', async () => {
    const { container, unmount } = await renderShellApproval();
    await typeNote(container, '  That file is in ~/Documents, not here.  ');
    await press(container, 'Deny');

    expect(submitApprovalDecision).toHaveBeenCalledTimes(1);
    expect(submitApprovalDecision.mock.calls[0][0]).toMatchObject({
      approved: false,
      user_note: 'That file is in ~/Documents, not here.',
    });
    unmount();
  });

  it('sends the note with an approval too', async () => {
    const { container, unmount } = await renderShellApproval();
    await typeNote(container, 'Approve, but also check the exit code.');
    await press(container, 'Approve');

    expect(submitApprovalDecision.mock.calls[0][0]).toMatchObject({
      approved: true,
      user_note: 'Approve, but also check the exit code.',
    });
    unmount();
  });

  it('offers only Deny and Approve to decide with, and the note label names exactly those', async () => {
    const { container, unmount } = await renderShellApproval();

    expect(Array.from(container.querySelectorAll('.decision-btn')).map(button => button.textContent)).toEqual(['Deny', 'Approve']);
    expect(container.querySelector('.approval-note-region')?.getAttribute('aria-hidden')).toBe('true');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.approval-note-toggle')?.click();
    });
    expect(container.querySelector('.approval-note-region')?.hasAttribute('aria-hidden')).toBe(false);
    expect(container.textContent).toContain('Note to the agent (optional, sent with Approve or Deny)');
    unmount();
  });

  it('starts the note as a single link, opens it into a focused field, and closes it again with the same link', async () => {
    const { container, unmount } = await renderShellApproval();
    document.body.appendChild(container);
    const toggle = () => container.querySelector<HTMLButtonElement>('.approval-note-toggle');
    const region = () => container.querySelector('.approval-note-region');
    expect(toggle()?.textContent).toBe('Add a note for the agent');
    expect(toggle()?.getAttribute('aria-expanded')).toBe('false');
    expect(region()?.getAttribute('aria-hidden')).toBe('true');

    await act(async () => {
      toggle()?.click();
    });
    const textarea = container.querySelector<HTMLTextAreaElement>('textarea.approval-note-input');
    expect(toggle()?.textContent).toBe('Hide note');
    expect(toggle()?.getAttribute('aria-expanded')).toBe('true');
    expect(region()?.hasAttribute('aria-hidden')).toBe(false);
    // Focus waits one frame for the region to become visible, because a hidden field cannot take focus.
    await act(async () => {
      await new Promise(resolve => requestAnimationFrame(() => resolve(undefined)));
    });
    expect(document.activeElement).toBe(textarea);

    await act(async () => {
      toggle()?.click();
    });
    expect(toggle()?.textContent).toBe('Add a note for the agent');
    expect(toggle()?.getAttribute('aria-expanded')).toBe('false');
    expect(region()?.getAttribute('aria-hidden')).toBe('true');
    container.remove();
    unmount();
  });

  it('keeps a typed note when it is hidden, says so on the link, and still sends it', async () => {
    const { container, unmount } = await renderShellApproval();
    const toggle = () => container.querySelector<HTMLButtonElement>('.approval-note-toggle');
    await typeNote(container, 'Check the exit code.');
    expect(container.querySelector<HTMLTextAreaElement>('textarea.approval-note-input')?.value).toBe('Check the exit code.');

    await act(async () => {
      toggle()?.click();
    });
    expect(container.querySelector('.approval-note-region')?.getAttribute('aria-hidden')).toBe('true');
    expect(toggle()?.textContent).toBe('Show your note (it will be sent)');
    expect(container.querySelector<HTMLTextAreaElement>('textarea.approval-note-input')?.value).toBe('Check the exit code.');

    await press(container, 'Approve');
    expect(submitApprovalDecision.mock.calls[0][0]).toMatchObject({ approved: true, user_note: 'Check the exit code.' });
    unmount();
  });

  it('does not claim a hidden note when the field holds only whitespace', async () => {
    const { container, unmount } = await renderShellApproval();
    await typeNote(container, '   ');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.approval-note-toggle')?.click();
    });
    expect(container.querySelector('.approval-note-toggle')?.textContent).toBe('Add a note for the agent');
    unmount();
  });

  it('omits the note entirely when it is empty or only whitespace', async () => {
    const { container, unmount } = await renderShellApproval();
    await typeNote(container, '   ');
    await press(container, 'Deny');

    expect(submitApprovalDecision.mock.calls[0][0].user_note).toBeUndefined();
    unmount();
  });

  it('offers the note field for shell approvals but not for provider permissions or sensitive browser fills', () => {
    const shell = renderToStaticMarkup(<ApprovalOverlay agentTaskId="task-1" approval={shellApproval} rememberChoice={false} />);
    const provider = renderToStaticMarkup(<ApprovalOverlay agentTaskId="task-1" approval={providerApproval} rememberChoice={false} />);
    const browser = renderToStaticMarkup(
      <ApprovalOverlay
        agentTaskId="task-1"
        approval={{ ...shellApproval, execution_type: 'browser_sensitive_fill' }}
        rememberChoice={false}
      />,
    );

    expect(shell).toContain('approval-note-toggle');
    expect(provider).not.toContain('approval-note-toggle');
    expect(browser).not.toContain('approval-note-toggle');
    expect(provider).not.toContain('approval-note-input');
    expect(browser).not.toContain('approval-note-input');
  });
});

describe('ApprovalOverlay settings change approval', () => {
  const settingsApproval: ExecutionApprovalRequest = {
    approval_id: 'settings-1',
    agent_task_id: 'task-1',
    command: 'Change Basil settings. Open turns: single to multiple',
    reason: 'The user wants to compare turns.',
    risk_level: 'medium',
    generalized_pattern: 'settings_change:appearance.agent_task_chain_expansion',
    execution_type: 'settings_change',
    whitelist: { eligible: false, reason: 'Settings changes are approved one at a time and cannot be remembered.', advice: null },
    settings_change: {
      tier: 'behavioral',
      changes: [{ key: 'appearance.agent_task_chain_expansion', label: 'Open turns in a task chain', before: 'single', after: 'multiple' }],
    },
  };

  it('shows the before and after values, and neither a remember checkbox, a note field, nor the raw pattern', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={settingsApproval} rememberChoice={false} />,
    );

    expect(markup).toContain('Settings Change Approval Required');
    expect(markup).toContain('Open turns in a task chain');
    expect(markup).toContain('single');
    expect(markup).toContain('multiple');
    expect(markup).toContain('cannot be remembered');
    expect(markup).not.toContain('Remember this choice');
    expect(markup).not.toContain('approval-note-input');
    expect(markup).not.toContain('approval-note-toggle');
    expect(markup).not.toContain('Pattern:');
    expect(markup).not.toContain('command-display');
  });

  it('falls back to the summary line when the diff is missing', () => {
    const markup = renderToStaticMarkup(
      <ApprovalOverlay agentTaskId="task-1" approval={{ ...settingsApproval, settings_change: undefined }} rememberChoice={false} />,
    );

    expect(markup).toContain('Change Basil settings. Open turns: single to multiple');
  });

  it('answers through the settings-change endpoint, with no command fields', async () => {
    submitSettingsChangeApproval.mockResolvedValue({ success: true, message: 'ok' });
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={settingsApproval} rememberChoice={false} />);
    });

    const deny = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Deny');
    await act(async () => {
      deny?.click();
    });

    expect(submitSettingsChangeApproval).toHaveBeenCalledWith({ approval_id: 'settings-1', approved: false });
    expect(submitApprovalDecision).not.toHaveBeenCalled();
    act(() => root.unmount());
  });
});
