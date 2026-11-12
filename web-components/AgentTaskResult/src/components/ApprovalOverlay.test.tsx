// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ExecutionApprovalRequest } from '../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const submitApprovalDecision = vi.fn();
const submitBrowserSensitiveFillApproval = vi.fn();
const submitProviderPermissionDecision = vi.fn();
const submitSettingsChangeApproval = vi.fn();

vi.mock('../services/api', () => ({
  submitApprovalDecision,
  submitBrowserSensitiveFillApproval,
  submitProviderPermissionDecision,
  submitSettingsChangeApproval,
}));

vi.mock('../store/agentStore', () => ({
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

  it("shows the agent's explanation, its recommendation, and the script path beside the script toggle", () => {
    const markup = render(explained);

    expect(markup).toContain('What this does');
    expect(markup).toContain('Builds the weekly report from the exported CSV.');
    expect(markup).toContain('The agent&#x27;s explanation');
    expect(markup).toContain('The agent&#x27;s recommendation:');
    expect(markup).toContain('Ask me each time');
    expect(markup).toContain('It is a script.');
    expect(markup).toContain('View full script (2 lines)');
    expect(markup).toContain('/tmp/report.sh');
  });

  it('hides the remember checkbox and says why when the command can never be remembered', () => {
    const markup = render(explained);

    expect(markup).not.toContain('Remember this choice');
    expect(markup).toContain('This approval applies to this run only.');
    expect(markup).toContain('A bare bash would allow any command or script');
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

  it('says when Basil overrode the agent', () => {
    const markup = render({
      ...explained,
      whitelist: {
        eligible: false,
        reason: 'python can run any code.',
        advice: { recommend: false, reason: 'python can run any code.', downgraded: true },
      },
    });

    expect(markup).toContain('Basil overrode the agent here');
  });

  it('recommends remembering only when the agent says yes and the command is eligible', () => {
    const markup = render({
      ...shellApproval,
      purpose: 'Lists the folder.',
      whitelist: { eligible: true, reason: '', advice: { recommend: true, reason: 'Read-only and narrow.', downgraded: false } },
    });

    expect(markup).toContain('Remember this choice');
    expect(markup).toContain('Read-only and narrow.');
    expect(markup).not.toContain('This approval applies to this run only.');
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
    expect(markup).toContain('This approval applies to this run only.');
  });

  it('offers a connected tool as always allow for that one tool, with no command pattern', () => {
    const markup = render({
      ...shellApproval,
      command: 'mcp:Gmail:label_message({"messageId":"AAA"})',
      generalized_pattern: 'mcp:Gmail:label_message({messageId:AAA})',
      purpose: 'Adds the Receipts label to one message.',
      whitelist: {
        eligible: true,
        reason: '',
        advice: null,
        pattern: '',
        broad: false,
        tool_policy: { connection_id: 'conn-gmail', connection_name: 'Gmail', tool_name: 'label_message', destructive: false },
      },
    });

    expect(markup).toContain('Always allow label_message on Gmail');
    expect(markup).toContain('This changes only this tool. You can undo it in Settings');
    expect(markup).not.toContain('Remember this choice');
    expect(markup).not.toContain('Pattern: ');
    expect(markup).not.toContain('If remembered');
    expect(markup).not.toContain('approval-tool-destructive');
  });

  it('warns before always allowing a connected tool that deletes or sends', () => {
    const markup = render({
      ...shellApproval,
      command: 'mcp:Gmail:trash_message({"messageId":"AAA"})',
      generalized_pattern: 'mcp:Gmail:trash_message({messageId:AAA})',
      purpose: 'Moves one message to Trash.',
      whitelist: {
        eligible: true,
        reason: '',
        advice: null,
        pattern: '',
        broad: false,
        tool_policy: { connection_id: 'conn-gmail', connection_name: 'Gmail', tool_name: 'trash_message', destructive: true },
      },
    });

    expect(markup).toContain('approval-tool-destructive');
    expect(markup).toContain('This tool deletes or sends things.');
    expect(markup).toContain('<code class="approval-pattern__words">trash_message</code>');
    expect(markup).toContain('Always allow trash_message on Gmail');
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
    expect(markup).not.toContain('The agent&#x27;s recommendation:');
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

  it('leads with the explanation and shows only a short preview of a long command', () => {
    const markup = render(withPurpose);

    expect(markup.indexOf('Lists the subjects in your inbox.')).toBeLessThan(markup.indexOf('osascript get-inbox'));
    expect(markup).toContain('Show full command');
    expect(markup).not.toContain(longCommand);
    expect(markup).toContain(`${longCommand.slice(0, 80).trimEnd()}…`);
  });

  it('shows a short command in full with no expander', () => {
    const markup = render({ ...shellApproval, purpose: 'Lists the folder.' });

    expect(markup).toContain('ls -la');
    expect(markup).not.toContain('Show full command');
    expect(markup).not.toContain('…');
  });

  it('previews only the first line of a multi-line command and reveals the rest on expand', async () => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const multiLine = 'echo one\necho two\necho three';
    await act(async () => {
      root.render(<ApprovalOverlay agentTaskId="task-1" approval={{ ...shellApproval, command: multiLine, purpose: 'Echoes.' }} rememberChoice={false} />);
    });

    expect(container.querySelector('.command-display')?.textContent).toBe('echo one…');
    const toggle = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Show full command');
    await act(async () => {
      toggle?.click();
    });
    expect(container.querySelector('.command-display')?.textContent).toBe(multiLine);
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

    expect(Array.from(container.querySelectorAll('button')).map(button => button.textContent)).toEqual(['Deny', 'Approve']);
    expect(container.textContent).toContain('Note to the agent (optional, sent with Approve or Deny)');
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

    expect(shell).toContain('approval-note-input');
    expect(shell).toContain('maxLength="2000"');
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
