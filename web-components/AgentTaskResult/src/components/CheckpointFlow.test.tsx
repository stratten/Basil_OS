// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import type { CheckpointData } from '../types';

let CheckpointFlow: typeof import('./CheckpointFlow').default;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  CheckpointFlow = (await import('./CheckpointFlow')).default;
});

const checkpoint: CheckpointData = {
  checkpoint_id: 'checkpoint-1',
  prompt: '## Review\n\nPlease **confirm** the plan.',
  input_type: 'confirmation',
};

describe('CheckpointFlow presentation', () => {
  it('uses compact checkpoint markdown and separate overlay regions', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={checkpoint} mode="overlay" />
    );

    expect(markup).toContain('checkpoint-flow-content--overlay');
    expect(markup).toContain('checkpoint-prompt-details');
    expect(markup).toContain('checkpoint-response-controls');
    expect(markup).toContain('result-section--checkpoint');
    expect(markup).toContain('Review Output');
  });

  it('keeps inline checkpoints out of overlay layout and review mode', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={checkpoint} mode="inline" />
    );

    expect(markup).not.toContain('checkpoint-flow-content--overlay');
    expect(markup).not.toContain('Review Output');
  });

  it('toggles an overlay into a non-modal review dock and preserves an entered clarification', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const reviewCheckpoint: CheckpointData = {
      checkpoint_id: 'review-choice',
      prompt: 'Review the generated output before choosing.',
      input_type: 'choice',
      options: [{ id: 'option-a', label: 'Use the first option', value: 'option-a' }],
    };

    try {
      act(() => {
        root.render(<CheckpointFlow agentTaskId="task-1" checkpoint={reviewCheckpoint} mode="overlay" />);
      });

      const reviewButton = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Review Output');
      const clarificationInput = container.querySelector<HTMLTextAreaElement>('#checkpoint-clarification-input');
      expect(reviewButton).toBeDefined();
      expect(clarificationInput).toBeDefined();

      act(() => {
        if (clarificationInput) {
          const valueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
          valueSetter?.call(clarificationInput, 'Use a different audience.');
          clarificationInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
      });

      act(() => {
        reviewButton?.click();
      });

      const reviewingDialog = container.querySelector<HTMLElement>('.agent-task-input-dialog');
      expect(container.querySelector('.agent-task-input-backdrop')?.classList.contains('agent-task-input-backdrop--reviewing-output')).toBe(true);
      expect(reviewingDialog?.classList.contains('agent-task-input-dialog--reviewing-output')).toBe(true);
      expect(reviewingDialog?.getAttribute('role')).toBe('region');
      expect(reviewingDialog?.hasAttribute('aria-modal')).toBe(false);
      expect(reviewButton?.textContent).toBe('Back to input');
      expect(container.querySelector<HTMLTextAreaElement>('#checkpoint-clarification-input')?.value).toBe('Use a different audience.');

      act(() => {
        reviewButton?.click();
      });

      const inputDialog = container.querySelector<HTMLElement>('.agent-task-input-dialog');
      expect(container.querySelector('.agent-task-input-backdrop')?.classList.contains('agent-task-input-backdrop--reviewing-output')).toBe(false);
      expect(inputDialog?.classList.contains('agent-task-input-dialog--reviewing-output')).toBe(false);
      expect(inputDialog?.getAttribute('role')).toBe('dialog');
      expect(inputDialog?.getAttribute('aria-modal')).toBe('true');
      expect(reviewButton?.textContent).toBe('Review Output');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('renders escaped checkpoint newlines as readable prompt breaks', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow
        agentTaskId="task-1"
        checkpoint={{
          checkpoint_id: 'escaped-newline',
          prompt: 'Drafts are ready.\\nHow would you like to proceed?',
          input_type: 'data',
        }}
        mode="inline"
      />
    );

    expect(markup).toContain('Drafts are ready.');
    expect(markup).toContain('How would you like to proceed?');
    expect(markup).not.toContain('\\n');
  });
});

const providerFormCheckpoint: CheckpointData = {
  checkpoint_id: 'interaction-1',
  prompt: 'Pick a strategy and describe why.',
  input_type: 'provider_form',
  fields: [
    {
      name: 'strategy',
      label: 'Strategy',
      kind: 'choice',
      required: true,
      options: [{ id: 'strategy-option-0', label: 'balanced', value: 'balanced' }],
    },
    { name: 'rationale', label: 'Rationale', kind: 'text', required: false },
  ],
  metadata: { source: 'provider_user_input', provider_run_id: 'run-1' },
};

describe('CheckpointFlow provider_form presentation', () => {
  it('renders one semantic control group per field and marks required fields', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={providerFormCheckpoint} mode="inline" />
    );

    expect(markup).toContain('checkpoint-provider-form');
    expect(markup).toContain('<fieldset class="checkpoint-provider-form-field">');
    expect(markup).toContain('<legend class="checkpoint-provider-form-field-label">Strategy');
    expect(markup).toContain('checkpoint-choice-card');
    expect(markup).toContain('for="checkpoint-provider-field-rationale"');
    expect(markup).toContain('id="checkpoint-provider-field-rationale"');
    expect(markup).not.toContain('Cancel delegation');
  });

  it('disables Continue until every required field has a value', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={providerFormCheckpoint} mode="inline" />
    );

    expect(markup).toContain('disabled=""');
  });

  it('keeps final provider-form actions outside the scrollable response details', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={providerFormCheckpoint} mode="overlay" />,
    );

    const scrollRegionIndex = markup.indexOf('checkpoint-response-scroll-region');
    const submitActionsIndex = markup.indexOf('checkpoint-submit-actions');
    expect(scrollRegionIndex).toBeGreaterThan(-1);
    expect(submitActionsIndex).toBeGreaterThan(scrollRegionIndex);
    expect(markup).toContain('checkpoint-provider-form');
    expect(markup).toContain('checkpoint-review-output-actions');
    expect(markup).toContain('checkpoint-submit-actions');
  });
});

const choiceCheckpoint: CheckpointData = {
  checkpoint_id: 'choice-1',
  prompt: 'Which target should Basil use?',
  input_type: 'choice',
  options: [
    { id: 'option-a', label: 'Provider A', value: 'target-choice:a', description: 'Workspace A' },
    { id: 'option-b', label: 'Provider B', value: 'target-choice:b', description: 'Workspace B' },
  ],
};

describe('CheckpointFlow generic choice presentation', () => {
  it('renders cards, an accessible clarification field, and Continue', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={choiceCheckpoint} mode="inline" />
    );

    expect(markup).toContain('Provider A');
    expect(markup).toContain('Provider B');
    expect(markup).toContain('for="checkpoint-clarification-input"');
    expect(markup).toContain('checkpoint-clarification-help');
    expect(markup).toContain('Describe a different target or the clarification needed.');
    expect(markup).toContain('Continue');
  });

  it('keeps the clarification field available when no choice cards exist', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow
        agentTaskId="task-1"
        checkpoint={{
          checkpoint_id: 'choice-without-options',
          prompt: 'Which target should Basil use?',
          input_type: 'choice',
          options: [],
        }}
        mode="inline"
      />
    );

    expect(markup).toContain('Different target or clarification');
    expect(markup).toContain('Continue');
  });
});

const targetAuthorizationCheckpoint: CheckpointData = {
  checkpoint_id: 'auth-1',
  prompt: 'Which provider and authorized workspace should Basil use for this delegation?',
  input_type: 'choice',
  options: [
    {
      id: 'target-option-1',
      label: 'Fixture Provider — Workspace grant-a',
      value: 'target-choice:token-1',
      description: 'Primary repository',
    },
  ],
  metadata: {
    source: 'provider_target_authorization',
    authorization_id: 'auth-1',
    cancel_value: 'target-cancel:token-1',
  },
};

describe('CheckpointFlow provider target authorization presentation', () => {
  it('renders cancel delegation, cards, and clarification without provider-form controls', () => {
    const markup = renderToStaticMarkup(
      <CheckpointFlow agentTaskId="task-1" checkpoint={targetAuthorizationCheckpoint} mode="inline" />
    );

    expect(markup).toContain('Cancel delegation');
    expect(markup).toContain('Different target or clarification');
    expect(markup).toContain('Fixture Provider — Workspace grant-a');
    expect(markup).not.toContain('checkpoint-provider-form');
  });
});
