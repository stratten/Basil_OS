import CompanionFocusField from './CompanionFocusField';
import CompanionPaneHeader from './CompanionPaneHeader';
import CompanionScreenShareNote from './CompanionScreenShareNote';
import CompanionSources from './CompanionSources';
import type { CompanionController } from './useCompanion';
import type { CompanionGlobalSettingsController } from './useCompanionGlobalSettings';

interface CompanionSetupPaneProps {
  controller: CompanionController;
  globalSettings: CompanionGlobalSettingsController;
  onClose: () => void;
}

/** Shown while the Companion switch is on before a recording starts: the place to set a focus and queue folders or files so the Companion is ready the moment the recording begins. */
export default function CompanionSetupPane({ controller, globalSettings, onClose }: CompanionSetupPaneProps) {
  const { settings, update } = globalSettings;
  return (
    <aside className="companion-pane companion-pane--embedded" aria-label="Companion setup">
      <CompanionPaneHeader canDetach={false} onCollapse={onClose} />
      <div className="meeting-status-row companion-status-row" role="status">
        <span className="meeting-connection-indicator meeting-connection-indicator--ready" aria-hidden="true" />
        <span className="meeting-status-message">Ready. The Companion starts with your next recording.</span>
      </div>
      {controller.actionError && (
        <div className="meeting-history-load-more-error" role="alert">
          <span>{controller.actionError}</span>
          <button type="button" onClick={controller.clearActionError}>Dismiss</button>
        </div>
      )}
      <div className="companion-scroll">
        <CompanionScreenShareNote {...globalSettings} />
        {settings && <CompanionFocusField value={settings.next_focus} onSave={(next) => update({ next_focus: next })} />}
        <CompanionSources
          roots={[]}
          pendingRoots={controller.pendingRoots}
          canEdit
          onAddPaths={controller.addRoots}
          onRemoveRoot={controller.removeRoot}
          onRemovePending={controller.removePendingRoot}
        />
      </div>
    </aside>
  );
}
