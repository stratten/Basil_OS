import { useId, useState } from 'react';
import CollapsibleRegion from '@shared/disclosure/CollapsibleRegion';
import type { UserInteraction } from './userInteractions';

/** The body of a "Basil asked to run" card: the agent's explanation first, then a "Show command" button that opens the full command, and any script, which opens the same way. No one-line preview of the command is shown, since it was visual noise in the middle of every card. */
export default function ApprovalRequestDetails({ interaction }: { interaction: UserInteraction }) {
  const [commandExpanded, setCommandExpanded] = useState(false);
  const [scriptExpanded, setScriptExpanded] = useState(false);
  const scriptRegionId = useId();
  const commandText = interaction.prompt;
  const commandRegionId = useId();
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

      {/* The command region is the zero-height case of the height animation the script uses, so opening it grows the full command from nothing. */}
      <button
        type="button"
        className="interaction-approval-toggle"
        aria-expanded={commandExpanded}
        aria-controls={commandRegionId}
        onClick={() => setCommandExpanded(!commandExpanded)}
      >
        {commandExpanded ? 'Hide command' : 'Show command'}
      </button>
      <CollapsibleRegion expanded={commandExpanded} id={commandRegionId}>
        <div className="interaction-exchange-command">{commandText}</div>
      </CollapsibleRegion>

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
            aria-controls={scriptRegionId}
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
          <CollapsibleRegion expanded={scriptExpanded} id={scriptRegionId}>
            <pre className="interaction-exchange-command interaction-approval-script-text">{scriptContent}</pre>
          </CollapsibleRegion>
        </div>
      )}
    </div>
  );
}
