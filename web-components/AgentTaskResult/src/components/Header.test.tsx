import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { BASIL_TEAM } from '../copy/teamIdentity';

let Header: typeof import('./Header').default;

beforeAll(async () => {
  vi.stubGlobal('window', {});
  Header = (await import('./Header')).default;
});

function renderHeader(overrides: Partial<Parameters<typeof Header>[0]> = {}): string {
  return renderToStaticMarkup(
    <Header
      isProcessing
      isCapturing={false}
      bubbleMode="ambient"
      baseColor="#33559B"
      accentColor="#FFFFFF"
      {...overrides}
    />
  );
}

describe('Header collapsed status', () => {
  it('keeps the title and renders a subordinate status while collapsed', () => {
    const markup = renderHeader({
      isCollapsed: true,
      collapsedTaskTitle: 'Investigate Folder Size',
      collapsedStatusText: 'Planning\\nExecuting',
    });

    expect(markup).toContain(BASIL_TEAM.agentTask.displayName);
    expect(markup).toContain('header-collapsed-task-title');
    expect(markup).toContain('Investigate Folder Size');
    expect(markup).toContain('header-collapsed-status');
    expect(markup).toContain('Planning\nExecuting');
    expect(markup).toContain('data-agent-task-header-controls="true"');
    expect(markup).toContain('data-agent-task-header-identity="true"');
    expect(markup).toContain('data-agent-task-header-bubble="true"');
  });

  it('keeps the title without a subordinate status when no status exists', () => {
    const markup = renderHeader({ isCollapsed: true });

    expect(markup).toContain(BASIL_TEAM.agentTask.displayName);
    expect(markup).not.toContain('header-collapsed-status');
  });

  it('reserves stop-control space only when a stop action is available', () => {
    const withoutStop = renderHeader({ isCollapsed: true });
    const unavailableStop = renderHeader({ isCollapsed: true, showCancelStop: true });
    const withStop = renderHeader({ isCollapsed: true, showCancelStop: true, onCancelRunning: vi.fn() });

    expect(withoutStop).toContain('class="header-right"');
    expect(unavailableStop).toContain('class="header-right"');
    expect(withStop).toContain('class="header-right has-stop-action"');
  });

  it('keeps long collapsed content in the DOM while Stop uses hover-disclosed space', () => {
    const markup = renderHeader({
      isCollapsed: true,
      collapsedTaskTitle: 'Investigate a deliberately long task title without idle truncation',
      collapsedStatusText: 'Reviewing a deliberately long current status message',
      showCancelStop: true,
      onCancelRunning: vi.fn(),
    });

    expect(markup).toContain('Investigate a deliberately long task title without idle truncation');
    expect(markup).toContain('Reviewing a deliberately long current status message');
    expect(markup).toContain('class="header-right has-stop-action"');
    expect(markup).toContain('>Stop</button>');
  });

  it('omits only the task subtitle when the generated title is absent', () => {
    const markup = renderHeader({
      isCollapsed: true,
      collapsedStatusText: 'Reading screen context',
    });

    expect(markup).toContain(BASIL_TEAM.agentTask.displayName);
    expect(markup).not.toContain('header-collapsed-task-title');
    expect(markup).toContain('header-collapsed-status');
  });

  it('does not render collapsed status while expanded', () => {
    const markup = renderHeader({
      isCollapsed: false,
      collapsedTaskTitle: 'Investigate Folder Size',
      collapsedStatusText: 'Planning',
    });

    expect(markup).toContain(BASIL_TEAM.agentTask.displayName);
    expect(markup).not.toContain('header-collapsed-task-title');
    expect(markup).not.toContain('header-collapsed-status');
  });

  it('hides close and minimize controls when hideWindowControls is true', () => {
    const markup = renderHeader({ hideWindowControls: true });

    expect(markup).not.toContain('title="Close"');
    expect(markup).not.toContain('title="Minimize"');
    expect(markup).toContain('header-team-icon');
    expect(markup).toContain('header-bubble');
  });

  it('uses the compact Board toolbar with the Conversation-style Stop control when embedded', () => {
    const markup = renderHeader({
      embedded: true,
      taskTitle: 'Investigate Folder Size',
      showCancelStop: true,
      onCancelRunning: vi.fn(),
    });

    expect(markup).toContain('embedded-task-toolbar');
    expect(markup).toContain('Investigate Folder Size');
    expect(markup).toContain('basil-stop-action');
    expect(markup).toContain('>Stop</button>');
    expect(markup).not.toContain('header-stop-icon');
    expect(markup).not.toContain('header-bubble');
    expect(markup).not.toContain('title="Close"');
    expect(markup).not.toContain('title="Minimize"');
    expect(markup).not.toContain('header-team-icon');
    expect(markup).not.toContain('Open in a separate window');
  });

  it('strips Markdown syntax from the embedded task title', () => {
    const markup = renderHeader({
      embedded: true,
      taskTitle: '**Amazon Order:** [Vibe & Celsius](https://amazon.example)',
    });

    expect(markup).toContain('Amazon Order: Vibe &amp; Celsius');
    expect(markup).not.toContain('**');
    expect(markup).not.toContain('https://amazon.example');
  });

  it('uses the same visible Stop and disabled Stopping control in the standalone header', () => {
    const activeMarkup = renderHeader({
      showCancelStop: true,
      onCancelRunning: vi.fn(),
    });
    const cancellingMarkup = renderHeader({
      showCancelStop: true,
      isCancelling: true,
      onCancelRunning: vi.fn(),
    });

    expect(activeMarkup).toContain('basil-stop-action');
    expect(activeMarkup).toContain('>Stop</button>');
    expect(activeMarkup).not.toContain('header-stop-icon');
    expect(cancellingMarkup).toContain('>Stopping</button>');
    expect(cancellingMarkup).toContain('disabled=""');
    expect(cancellingMarkup).toContain('class="header-right has-stop-action is-stopping"');
  });
});
