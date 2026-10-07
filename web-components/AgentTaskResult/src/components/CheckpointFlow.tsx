import { useState } from 'react';
import type { BrowserPermissionRepairMetadata, CheckpointData, CheckpointField, CheckpointOption, ProviderTargetAuthorizationMetadata } from '../types';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import AgentTaskInputSurface from './AgentTaskInputSurface';
import MarkdownRenderer from './MarkdownRenderer';
import {
  formatCheckpointAnswer,
  isValidNumericAnswer,
  orderSelectedValues,
  toggleCheckpointSelection,
} from './checkpointAnswer';

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

// A single selectable checkpoint option, rendered as a card. A radio or checkbox indicator marks single- or multi-select choices; confirmation cards submit on click and show no indicator.
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

// Yes/No options for binary confirmation checkpoints. Rendered as cards that
// submit on click (no separate Continue step) using explicit values, which
// avoids the prior setUserInput-then-submit state race.
const CONFIRMATION_OPTIONS: CheckpointOption[] = [
  { id: 'yes', label: 'Yes', value: 'yes', variant: 'primary' },
  { id: 'no', label: 'No', value: 'no', variant: 'default' },
];

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
  const [isReviewingOutput, setIsReviewingOutput] = useState(false);
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
  const numericInputInvalid = isNumericCheckpoint && userInput.trim() !== '' && !isValidNumericAnswer(userInput);
  const canSubmit = isProviderFormCheckpoint
    ? !missingRequiredProviderField
    : isChoiceCheckpoint
      ? selectedValues.length > 0 || trimmedOtherText.length > 0
      : isConfirmationCheckpoint
        ? trimmedOtherText.length > 0
        : userInput.trim().length > 0 && !numericInputInvalid;

  // Accepts an explicit value so card clicks (especially Yes/No) submit the
  // intended response immediately instead of relying on async setUserInput
  // having flushed before submission.
  const handleSubmit = async (explicitValue?: string) => {
    const response = explicitValue ?? (
      isChoiceCheckpoint || isConfirmationCheckpoint
        ? formatCheckpointAnswer({
          selectedValues: orderSelectedValues(checkpoint.options || [], selectedValues),
          otherText,
          labeled: labeledAnswers,
        })
        : isNumericCheckpoint
          ? userInput.trim()
          : userInput
    );
    setSubmitting(true);
    try {
      agentStore.markCheckpointResumeProcessing(
        agentTaskId,
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
    } catch (err) {
      console.error('[Checkpoint] Submit failed:', err);
      agentStore.showCheckpoint(agentTaskId, checkpoint);
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
    }
    agentStore.hideCheckpoint(agentTaskId);
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
        ) : isConfirmationCheckpoint ? (
          <div className="checkpoint-choice-with-clarification">
            <div className="checkpoint-options checkpoint-options-row">
              {CONFIRMATION_OPTIONS.map(option => (
                <CheckpointChoiceCard
                  key={option.id}
                  option={option}
                  selected={false}
                  disabled={submitting}
                  indicator="none"
                  onSelect={value => handleSubmit(formatCheckpointAnswer({
                    selectedValues: [value],
                    otherText,
                    labeled: true,
                  }))}
                />
              ))}
            </div>
            {otherField}
          </div>
        ) : isChoiceCheckpoint ? (
          <div className="checkpoint-choice-with-clarification">
            {allowMultiple && (
              <p className="checkpoint-choice-hint">Select all that apply.</p>
            )}
            <div className="checkpoint-options">
              {(checkpoint.options || []).map(option => (
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
          />
        )}
      </div>

      </div>
      <div className="agent-task-input-actions checkpoint-submit-actions">
        {mode === 'overlay' && (
          <button
            type="button"
            className="action-btn checkpoint-review-output-action"
            onClick={handleReviewOutput}
            aria-pressed={isReviewingOutput}
            disabled={submitting}
            title="Look over the work Basil has done so far before you answer"
          >
            {isReviewingOutput ? 'Back to question' : 'See work so far'}
          </button>
        )}
        {targetAuthorizationMetadata && (
          <button
            className="action-btn"
            onClick={() => handleSubmit(targetAuthorizationMetadata.cancel_value)}
            disabled={submitting}
          >
            Cancel delegation
          </button>
        )}
        <button className="action-btn" onClick={handleCancel} disabled={submitting}>
          Skip
        </button>
        <button
          className="action-btn primary"
          onClick={() => handleSubmit()}
          disabled={submitting || !canSubmit}
        >
          {submitting ? 'Submitting...' : 'Continue'}
        </button>
      </div>
    </div>
  );

  const content = (
    <div className={`checkpoint-flow-content${mode === 'overlay' ? ' checkpoint-flow-content--overlay' : ''}`}>
      {promptDetails}
      {responseControls}
    </div>
  );

  if (mode === 'overlay') {
    return (
      <AgentTaskInputSurface
        eyebrow={isReviewingOutput ? 'Look over the work, then answer' : 'Input required'}
        isReviewingOutput={isReviewingOutput}
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
