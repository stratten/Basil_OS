import { useState } from 'react';
import { previewCommand } from '../approval/commandPreview';
import type { UserInteraction } from './userInteractions';

/** The body of a "Basil asked to run" card: the agent's explanation first, then a short command preview that expands to the full command and any script. */
export default function ApprovalRequestDetails({ interaction }: { interaction: UserInteraction }) {
  const [commandExpanded, setCommandExpanded] = useState(false);
  const [scriptExpanded, setScriptExpanded] = useState(false);
  const commandText = interaction.prompt;
  const { preview, previewable } = previewCommand(commandText);
  const scriptContent = interaction.scriptContent;
  const scriptLineCount = scriptContent ? scriptContent.split('\n').length : 0;

  return (
    <div className="interaction-approval">
      {interaction.purpose ? (
        <div className="interaction-approval-explanation">
          <div className="interaction-approval-explanation__label">What this does</div>
          <p className="interaction-approval-explanation__text">{interaction.purpose}</p>
          <div className="interaction-approval-explanation__source">{interaction.purposeSource === 'basil' ? "Basil's explanation" : "The agent's explanation"}</div>
        </div>
      ) : interaction.purposeMissing ? (
        <p className="interaction-approval-missing" role="note">
          The agent did not explain this command.
        </p>
      ) : null}

      <pre className="interaction-exchange-command">{commandExpanded || !previewable ? commandText : preview}</pre>
      {previewable && (
        <button
          type="button"
          className="interaction-approval-toggle"
          aria-expanded={commandExpanded}
          onClick={() => setCommandExpanded(!commandExpanded)}
        >
          {commandExpanded ? 'Hide full command' : 'Show full command'}
        </button>
      )}

      {interaction.scriptPath && !scriptContent && (
        <div className="interaction-approval-script-path">
          <span className="interaction-approval-script-path__label">Script file</span>{' '}
          <code>{interaction.scriptPath}</code>
        </div>
      )}
      {interaction.scriptNotice && !scriptContent && (
        <p className="interaction-approval-script-notice" role="note">{interaction.scriptNotice}</p>
      )}
      {scriptContent && (
        <div className="interaction-approval-script">
          <button
            type="button"
            className="interaction-approval-toggle"
            aria-expanded={scriptExpanded}
            onClick={() => setScriptExpanded(!scriptExpanded)}
          >
            {`${scriptExpanded ? 'Hide' : 'View'} full script (${scriptLineCount} lines${interaction.scriptTruncated ? ', shortened' : ''})`}
          </button>
          {interaction.scriptPath && (
            <div className="interaction-approval-script-path">
              <span className="interaction-approval-script-path__label">Script file</span>{' '}
              <code>{interaction.scriptPath}</code>
            </div>
          )}
          {interaction.scriptNotice && (
            <p className="interaction-approval-script-notice" role="note">{interaction.scriptNotice}</p>
          )}
          {scriptExpanded && (
            <pre className="interaction-exchange-command interaction-approval-script-text">{scriptContent}</pre>
          )}
        </div>
      )}
    </div>
  );
}
