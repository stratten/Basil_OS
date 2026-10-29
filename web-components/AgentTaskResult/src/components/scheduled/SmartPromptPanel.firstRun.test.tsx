// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SmartScheduleFields } from './SmartPromptPanel';

const mocks = vi.hoisted(() => ({ interpretScheduledAgentTaskPrompt: vi.fn() }));

vi.mock('../../services/api', () => ({
  interpretScheduledAgentTaskPrompt: mocks.interpretScheduledAgentTaskPrompt,
}));

let SmartPromptPanel: typeof import('./SmartPromptPanel').default;
let container: HTMLDivElement;
let root: Root;
let applied: SmartScheduleFields[];

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  SmartPromptPanel = (await import('./SmartPromptPanel')).default;
});

beforeEach(() => {
  mocks.interpretScheduledAgentTaskPrompt.mockReset();
  applied = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function interpretWith(scheduleConfig: Record<string, unknown>) {
  mocks.interpretScheduledAgentTaskPrompt.mockResolvedValue({
    success: true,
    title: 'Check inbox',
    agent_task_text: 'Check my inbox',
    schedule_type: 'recurring',
    schedule_config: scheduleConfig,
    timezone: 'UTC',
  });
  await act(async () => {
    root.render(
      <SmartPromptPanel userTimezone="UTC" busy={false} setBusy={vi.fn()} onApply={fields => applied.push(fields)} />,
    );
  });
  const textarea = container.querySelector('textarea')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  await act(async () => {
    setter.call(textarea, 'check my inbox every 30 minutes starting at 3pm');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const generate = Array.from(container.querySelectorAll('button')).find(b => b.textContent === 'Generate schedule')!;
  await act(async () => {
    generate.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

describe('SmartPromptPanel first run', () => {
  it('passes an interpreted first run through to the form', async () => {
    await interpretWith({ mode: 'interval', minutes: 30, start_at: '2030-01-01T15:00' });
    expect(applied[0]).toMatchObject({ mode: 'interval', intervalMinutes: 30, startAt: '2030-01-01T15:00' });
  });

  it('trims seconds and offsets so the datetime-local field accepts the value', async () => {
    await interpretWith({ mode: 'interval', minutes: 30, start_at: '2030-01-01T15:00:00+00:00' });
    expect(applied[0].startAt).toBe('2030-01-01T15:00');
  });

  it('leaves startAt unset when the model gave no first run or a malformed one', async () => {
    await interpretWith({ mode: 'interval', minutes: 30, start_at: 'around three' });
    expect(applied[0].startAt).toBeUndefined();
  });

  it('shows the processing bubble beside the status line while interpreting', async () => {
    let resolveInterpret: (value: { success: boolean }) => void = () => {};
    mocks.interpretScheduledAgentTaskPrompt.mockReturnValue(new Promise((resolve) => {
      resolveInterpret = resolve;
    }));
    await act(async () => {
      root.render(
        <SmartPromptPanel userTimezone="UTC" busy={false} setBusy={vi.fn()} onApply={fields => applied.push(fields)} />,
      );
    });
    const textarea = container.querySelector('textarea')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    await act(async () => {
      setter.call(textarea, 'check my inbox every weekday at 8am');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const generate = Array.from(container.querySelectorAll('button')).find(b => b.textContent === 'Generate schedule')!;
    await act(async () => {
      generate.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const status = container.querySelector('.smart-prompt-interpreting');
    expect(status?.textContent).toContain('Interpreting your request');
    expect(status?.querySelector('canvas')).not.toBeNull();
    expect(container.querySelector('.loading-spinner')).toBeNull();
    expect(generate.textContent).toBe('Interpreting…');
    await act(async () => {
      resolveInterpret({ success: false });
    });
  });
});
