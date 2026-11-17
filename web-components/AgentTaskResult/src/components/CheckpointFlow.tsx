import { useState, type KeyboardEvent } from 'react';
import type { BrowserPermissionRepairMetadata, CheckpointData, CheckpointField, CheckpointOption, ProviderTargetAuthorizationMetadata } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import AgentTaskInputSurface from './AgentTaskInputSurface';
import { DecisionActions, DecisionButton } from './interaction/DecisionButton';
import {
  ContinueCircleIcon,
  SkipCircleIcon,
  StopCircleIcon,
  WorkLogCircleIcon,
} from '@shared/CircleControlIcons';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import MarkdownRenderer from './MarkdownRenderer';
import {
  formatCheckpointAnswer,
  isValidNumericAnswer,
  orderSelectedValues,
  toggleCheckpointSelection,
} from './checkpointAnswer';

/** First meaningful line of the prompt as plain text, for the docked card; the full prompt stays in the question itself. */
export function checkpointPromptSummary(prompt: string | undefined): string {
  return normalizeCheckpointPromptForDisplay(prompt ?? '')
    .split('\n')
    .map(line => plainMarkdownText(line).trim())
    .find(Boolean) ?? '';
}

interface Props {
  agentTaskId: string;
  checkpoint: CheckpointData;
  mode: 'overlay' | 'inline';
}

type ChoiceIndicator = 'radio' | 'checkbox' | 'none';

interface ChoiceCardProps {
  option: CheckpointOption;
  selected: boolean;
  disabled: boolean;
  indicator: ChoiceIndicator;
  onSelect: (value: string) => void;
}

// A single selectable checkpoint option, rendered as a card. A radio or checkbox indicator marks single- or multi-select choices; a confirmation is a single-select choice between Yes and No.
function CheckpointChoiceCard({ option, selected, disabled, indicator, onSelect }: ChoiceCardProps) {
  const variantClass =
    option.variant && option.variant !== 'default' ? ` ${option.variant}` : '';
  return (
    <button
      type="button"
      className={`checkpoint-choice-card${selected ? ' selected' : ''}${variantClass}`}
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => onSelect(option.value)}
    >
      {indicator !== 'none' && (
        <span
          className={`checkpoint-choice-indicator checkpoint-choice-indicator--${indicator}`}
          aria-hidden="true"
        />
      )}
      <span className="checkpoint-choice-body">
        <span className="checkpoint-choice-title">{option.label}</span>
        {option.description && (
          <span className="checkpoint-choice-description">{option.description}</span>
        )}
      </span>
    </button>
  );
}

// A confirmation checkpoint is a single-select choice between Yes and No, answered with the same Continue button as every other question. Whatever is typed in "Other" is sent along with the selection, so "yes, but..." and "no, do this instead" reach the agent intact.
const CONFIRMATION_OPTIONS: CheckpointOption[] = [
  { id: 'yes', label: 'Yes', value: 'yes' },
  { id: 'no', label: 'No', value: 'no' },
];

/** The longest label that still sits comfortably beside another option on one line. */
const INLINE_OPTION_LABEL_LIMIT = 24;

/** True when every option is a short label with no description, such as Yes and No, so the options can sit side by side instead of each taking a full row. */
export function optionsFitOnOneLine(options: CheckpointOption[]): boolean {
  return options.length > 0 && options.every(option => !option.description && option.label.length <= INLINE_OPTION_LABEL_LIMIT);
}

function isBrowserPermissionRepairMetadata(
  metadata: CheckpointData['metadata']
): metadata is BrowserPermissionRepairMetadata {
  return Boolean(metadata && metadata.source === 'browser_permission_repair');
}

function isProviderUserInputCheckpoint(checkpoint: CheckpointData): boolean {
  return Boolean(checkpoint.metadata?.source === 'provider_user_input' && checkpoint.fields?.length);
}

function isProviderTargetAuthorizationMetadata(
  metadata: CheckpointData['metadata']
): metadata is ProviderTargetAuthorizationMetadata {
  return Boolean(
    metadata
    && metadata.source === 'provider_target_authorization'
    && typeof metadata.authorization_id === 'string'
    && metadata.authorization_id.trim()
    && typeof metadata.cancel_value === 'string'
    && metadata.cancel_value.trim()
  );
}

interface ProviderFormFieldProps {
  field: CheckpointField;
  value: string;
  disabled: boolean;
  onChange: (name: string, value: string) => void;
}

function ProviderFormField({ field, value, disabled, onChange }: ProviderFormFieldProps) {
  const inputId = `checkpoint-provider-field-${field.name}`;
  const fieldLabel = (
    <>
      {field.label}
      {field.required && <span aria-hidden="true"> *</span>}
    </>
  );

  if (field.kind === 'choice' && field.options) {
    return (
      <fieldset className="checkpoint-provider-form-field">
        <legend className="checkpoint-provider-form-field-label">{fieldLabel}</legend>
        <div className="checkpoint-options">
          {field.options.map(option => (
            <CheckpointChoiceCard
              key={option.id}
              option={option}
              selected={value === option.value}
              disabled={disabled}
              indicator="radio"
              onSelect={selected => onChange(field.name, selected)}
            />
          ))}
        </div>
      </fieldset>
    );
  }

  return (
    <div className="checkpoint-provider-form-field">
      <label className="checkpoint-provider-form-field-label" htmlFor={inputId}>
        {fieldLabel}
      </label>
      <input
        id={inputId}
        type="text"
        className="text-followup-input checkpoint-provider-form-field-input"
        value={value}
        disabled={disabled}
        onChange={event => onChange(field.name, event.target.value)}
      />
    </div>
  );
}

function formatPermissionKind(permissionKind?: string) {
  switch (permissionKind) {
    case 'browser_javascript_from_apple_events':
      return 'Allow JavaScript from Apple Events';
    case 'macos_automation':
      return 'macOS Automation permission';
    default:
      return permissionKind || 'Browser automation permission';
  }
}

function BrowserPermissionRepairDetails({ metadata }: { metadata: BrowserPermissionRepairMetadata }) {
  return (
    <div className="browser-permission-repair">
      <div className="browser-permission-repair-title">
        Browser permission needed
      </div>
      <div className="browser-permission-repair-body">
        {metadata.browser || 'The browser'} needs {formatPermissionKind(metadata.permission_kind)} before Basil can continue DOM automation.
      </div>

      {Array.isArray(metadata.next_actions) && metadata.next_actions.length > 0 && (
        <ol className="browser-permission-repair-steps">
          {metadata.next_actions.map((action, index) => (
            <li key={`${index}-${action}`}>
              {action}
            </li>
          ))}
        </ol>
      )}

      {metadata.allow_foreground_option && (
        <div className="browser-permission-repair-warning">
          Foreground control may activate your visible browser and use keyboard or mouse actions. Basil will still route that through the foreground-control policy gate.
        </div>
      )}
    </div>
  );
}

function normalizeCheckpointPromptForDisplay(prompt: string): string {
  return prompt.replace(/\\r\\n/g, '\n').replace(/\\n/g, '\n');
}

export default function CheckpointFlow({ agentTaskId, checkpoint, mode }: Props) {
  const [userInput, setUserInput] = useState(checkpoint.default_value || '');
  const [selectedValues, setSelectedValues] = useState<string[]>([]);
  const [otherText, setOtherText] = useState('');
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    (checkpoint.fields || []).forEach(field => {
      if (field.default_value) initial[field.name] = field.default_value;
    });
    return initial;
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isReviewingOutput, setIsReviewingOutput] = useState(false);
  // Approvals (yes/no) open the details because the content is what is being approved; other questions keep them one click away.
  const [detailsOpen, setDetailsOpen] = useState(checkpoint.input_type === 'confirmation');
  const sessionAgentTaskId = checkpoint.session_agent_task_id || agentTaskId;
  const isClarificationCheckpoint = checkpoint.metadata?.source === 'clarification';
  const isProviderFormCheckpoint = isProviderUserInputCheckpoint(checkpoint);
  const targetAuthorizationMetadata = isProviderTargetAuthorizationMetadata(checkpoint.metadata)
    ? checkpoint.metadata
    : undefined;
  const isChoiceCheckpoint = checkpoint.input_type === 'choice';
  const browserPermissionMetadata = isBrowserPermissionRepairMetadata(checkpoint.metadata)
    ? checkpoint.metadata
    : undefined;
  const missingRequiredProviderField = isProviderFormCheckpoint
    ? (checkpoint.fields || []).some(field => field.required && !(fieldValues[field.name] || '').trim())
    : false;
  const isConfirmationCheckpoint = checkpoint.input_type === 'confirmation';
  const isNumericCheckpoint = checkpoint.input_type === 'data' && checkpoint.value_kind === 'numeric';
  // Target authorization resolves the reply verbatim as a choice token, cancel value, or new target, so it keeps one unlabeled answer.
  const labeledAnswers = !targetAuthorizationMetadata;
  const allowMultiple = isChoiceCheckpoint && checkpoint.allow_multiple === true && labeledAnswers;
  const trimmedOtherText = otherText.trim();
  const choiceOptions = isConfirmationCheckpoint ? CONFIRMATION_OPTIONS : (checkpoint.options || []);
  const numericInputInvalid = isNumericCheckpoint && userInput.trim() !== '' && !isValidNumericAnswer(userInput);
  const canSubmit = isProviderFormCheckpoint
    ? !missingRequiredProviderField
    : isChoiceCheckpoint || isConfirmationCheckpoint
      ? selectedValues.length > 0 || trimmedOtherText.length > 0
      : userInput.trim().length > 0 && !numericInputInvalid;

  // Accepts an explicit value for the provider-delegation cancel button, which submits a fixed answer without relying on async state having flushed.
  const handleSubmit = async (explicitValue?: string) => {
    const response = explicitValue ?? (
      isChoiceCheckpoint || isConfirmationCheckpoint
        ? formatCheckpointAnswer({
          selectedValues: orderSelectedValues(choiceOptions, selectedValues),
          otherText,
          labeled: labeledAnswers,
        })
        : isNumericCheckpoint
          ? userInput.trim()
          : userInput
    );
    setSubmitting(true);
    setSubmitError(null);
    try {
      // The card stays up, disabled, until the backend confirms it moved on; settling it below (or a resume event or a live read) is what makes it fade out.
      agentStore.beginCheckpointAnswer(
        agentTaskId,
        checkpoint.checkpoint_id,
        isClarificationCheckpoint ? 'Processing clarification...' : 'Resuming...'
      );
      agentStore.updateProgressStep(
        agentTaskId,
        isClarificationCheckpoint ? 'Processing clarification...' : 'Resuming...',
        true,
        false
      );
      if (isProviderFormCheckpoint) {
        await api.respondToProviderInteraction(
          sessionAgentTaskId,
          checkpoint.checkpoint_id,
          'accept',
          fieldValues
        );
      } else if (isClarificationCheckpoint) {
        await api.addClarification(sessionAgentTaskId, response);
      } else {
        await api.continueSession(sessionAgentTaskId, response);
      }
      // The answer was accepted, so a card that no resume event has cleared yet can leave now.
      agentStore.settleAnsweredCheckpoint(
        agentTaskId,
        checkpoint.checkpoint_id,
        isClarificationCheckpoint ? 'Processing clarification...' : 'Resuming...'
      );
    } catch (err) {
      console.error('[Checkpoint] Submit failed:', err);
      setSubmitError(err instanceof Error && err.message ? err.message : 'Your answer could not be sent. Try again.');
      agentStore.reopenCheckpointAfterFailedAnswer(agentTaskId, checkpoint);
      agentStore.updateStatus(agentTaskId, 'awaitingInput');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    if (isProviderFormCheckpoint) {
      api.respondToProviderInteraction(sessionAgentTaskId, checkpoint.checkpoint_id, 'cancel').catch(err => {
        console.error('[Checkpoint] Failed to cancel provider interaction:', err);
      });
      // A provider form is genuinely canceled, so there is nothing left to reopen.
      agentStore.hideCheckpoint(agentTaskId);
      return;
    }
    // The backend is still waiting for an answer, so the question is only set aside and can be reopened.
    agentStore.dismissCheckpoint(agentTaskId);
  };

  const handleReviewOutput = () => {
    setIsReviewingOutput(current => !current);
  };

  const handleFieldChange = (name: string, value: string) => {
    setFieldValues(previous => ({ ...previous, [name]: value }));
  };

  const handleChoiceSelect = (value: string) => {
    setSelectedValues(current => toggleCheckpointSelection(current, value, allowMultiple));
    if (!labeledAnswers) setOtherText('');
  };

  const handleOtherTextChange = (value: string) => {
    setOtherText(value);
    if (!labeledAnswers && value.trim()) setSelectedValues([]);
  };

  const otherField = (
    <div className="checkpoint-clarification">
      <label className="checkpoint-clarification-label" htmlFor="checkpoint-clarification-input">
        {targetAuthorizationMetadata ? 'Different target or clarification' : 'Other'}
      </label>
      {targetAuthorizationMetadata && (
        <p id="checkpoint-clarification-help" className="checkpoint-clarification-help">
          Use this when none of the options fits or you need Basil to change course.
        </p>
      )}
      <textarea
        id="checkpoint-clarification-input"
        className="text-followup-input checkpoint-clarification-input"
        value={otherText}
        onChange={e => handleOtherTextChange(e.target.value)}
        placeholder={
          targetAuthorizationMetadata
            ? 'Describe a different target or the clarification needed.'
            : 'Type a different answer or add a note for Basil.'
        }
        aria-describedby={targetAuthorizationMetadata ? 'checkpoint-clarification-help' : undefined}
        rows={3}
        disabled={submitting}
      />
    </div>
  );

  const promptDetails = (
    <div className="checkpoint-prompt-details">
      <div className="checkpoint-prompt">
        <MarkdownRenderer content={normalizeCheckpointPromptForDisplay(checkpoint.prompt)} variant="checkpoint" />
      </div>

      {checkpoint.details_markdown && (
        <details
          className="checkpoint-details"
          open={detailsOpen}
          onToggle={event => setDetailsOpen(event.currentTarget.open)}
        >
          <summary className="checkpoint-details-summary">{detailsOpen ? 'Hide details' : 'Show details'}</summary>
          <div className="checkpoint-prompt checkpoint-details-body">
            <MarkdownRenderer content={checkpoint.details_markdown} variant="checkpoint" />
          </div>
        </details>
      )}

      {browserPermissionMetadata && (
        <BrowserPermissionRepairDetails metadata={browserPermissionMetadata} />
      )}
    </div>
  );

  const responseControls = (
    <div className="checkpoint-response-controls">
      <div className="checkpoint-response-scroll-region">
      <div className="checkpoint-control-group">
        {isProviderFormCheckpoint && checkpoint.fields ? (
          <div className="checkpoint-provider-form">
            {checkpoint.fields.map(field => (
              <ProviderFormField
                key={field.name}
                field={field}
                value={fieldValues[field.name] || ''}
                disabled={submitting}
                onChange={handleFieldChange}
              />
            ))}
          </div>
        ) : isChoiceCheckpoint || isConfirmationCheckpoint ? (
          <div className="checkpoint-choice-with-clarification">
            {allowMultiple && (
              <p className="checkpoint-choice-hint">Select all that apply.</p>
            )}
            <div className={`checkpoint-options${optionsFitOnOneLine(choiceOptions) ? ' checkpoint-options--inline' : ''}`}>
              {choiceOptions.map(option => (
                <CheckpointChoiceCard
                  key={option.id}
                  option={option}
                  selected={selectedValues.includes(option.value)}
                  disabled={submitting}
                  indicator={allowMultiple ? 'checkbox' : 'radio'}
                  onSelect={handleChoiceSelect}
                />
              ))}
            </div>
            {otherField}
          </div>
        ) : isNumericCheckpoint ? (
          <div className="checkpoint-numeric">
            <input
              type="text"
              inputMode="decimal"
              className="text-followup-input checkpoint-numeric-input"
              value={userInput}
              onChange={e => setUserInput(e.target.value)}
              placeholder="Enter a number"
              aria-label="Numeric response"
              aria-invalid={numericInputInvalid}
              aria-describedby={numericInputInvalid ? 'checkpoint-numeric-error' : undefined}
              disabled={submitting}
            />
            {numericInputInvalid && (
              <p id="checkpoint-numeric-error" className="checkpoint-numeric-error" role="alert">
                Enter a number, such as 12 or 3.5.
              </p>
            )}
          </div>
        ) : (
          <textarea
            className="text-followup-input"
            value={userInput}
            onChange={e => setUserInput(e.target.value)}
            placeholder={
              checkpoint.input_type === 'data' ? 'Enter your response...'
              : checkpoint.input_type === 'file' ? 'Enter file path...'
              : checkpoint.input_type === 'review' ? 'Enter your review...'
              : 'Enter response...'
            }
            rows={3}
            disabled={submitting}
          />
        )}
        {submitError && (
          <p className="checkpoint-numeric-error" role="alert">
            {submitError}
          </p>
        )}
      </div>

      </div>
      <DecisionActions className="agent-task-input-actions checkpoint-submit-actions">
        {mode === 'overlay' && (
          <DecisionButton
            tone="neutral"
            icon={<WorkLogCircleIcon />}
            label={isReviewingOutput ? 'Back to question' : 'See work so far'}
            onClick={handleReviewOutput}
            pressed={isReviewingOutput}
            disabled={submitting}
            lead={!targetAuthorizationMetadata}
            title="look over what Basil has done before you answer"
            className="checkpoint-review-output-action"
          />
        )}
        {targetAuthorizationMetadata && (
          <DecisionButton
            tone="stop"
            icon={<StopCircleIcon />}
            label="Cancel delegation"
            onClick={() => handleSubmit(targetAuthorizationMetadata.cancel_value)}
            disabled={submitting}
            lead
            title="stop handing this work over and tell Basil so"
          />
        )}
        <DecisionButton
          tone="neutral"
          icon={<SkipCircleIcon />}
          label="Skip"
          onClick={handleCancel}
          disabled={submitting}
          title="set this question aside without answering. You can reopen it"
        />
        <DecisionButton
          tone="primary"
          icon={<ContinueCircleIcon />}
          label={submitting ? 'Submitting...' : 'Continue'}
          onClick={() => handleSubmit()}
          disabled={submitting || !canSubmit}
          title="send your answer (Command-Return)"
        />
      </DecisionActions>
    </div>
  );

  // Command-Return (or Control-Return) from any text field sends the answer, the same as the Continue button and as in the other answer boxes. It is claimed even when Continue is disabled, so a half-finished answer does not fall through to something else.
  const handleCommandReturn = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey) || event.nativeEvent.isComposing) return;
    if (!(event.target as HTMLElement).closest('textarea, input')) return;
    event.preventDefault();
    if (submitting || !canSubmit) return;
    void handleSubmit();
  };

  const content = (
    <div
      className={`checkpoint-flow-content${mode === 'overlay' ? ' checkpoint-flow-content--overlay' : ''}`}
      onKeyDown={handleCommandReturn}
    >
      {promptDetails}
      {responseControls}
    </div>
  );

  if (mode === 'overlay') {
    return (
      <AgentTaskInputSurface
        eyebrow="Input required"
        isReviewingOutput={isReviewingOutput}
        dockSummary={checkpointPromptSummary(checkpoint.prompt)}
        onResumeQuestion={handleReviewOutput}
      >
        {content}
      </AgentTaskInputSurface>
    );
  }

  return (
    <div className="agent-task-card checkpoint-inline-card">
      {content}
    </div>
  );
}
