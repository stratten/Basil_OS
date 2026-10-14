import NativeSymbolIcon from '../../../shared/NativeSymbolIcon';
import { openCompanionWindow } from '../bridge/meetingBridge';

interface CompanionPaneHeaderProps {
  onCollapse?: () => void;
  /** The setup pane has no live meeting to open in its own window yet. */
  canDetach: boolean;
}

/** The embedded Companion header: the History sidebar's title and icon-button treatment, with the same collapse glyph mirrored for a sidebar on the right edge. */
export default function CompanionPaneHeader({ onCollapse, canDetach }: CompanionPaneHeaderProps) {
  return (
    <div className="shared-history-sidebar-header companion-pane-header">
      <span className="shared-history-sidebar-title meeting-history-title">Companion</span>
      <span className="shared-history-sidebar-header-actions">
        {canDetach && (
          <button type="button" className="shared-history-sidebar-icon-button" aria-label="Detach Companion" title="Open the Companion in its own window" onClick={openCompanionWindow}>
            <NativeSymbolIcon name="openPreviewWindow" />
          </button>
        )}
        {onCollapse && (
          <button type="button" className="shared-history-sidebar-icon-button" aria-label="Hide the Companion" title="Hide the Companion" onClick={onCollapse}>
            <NativeSymbolIcon name="conversationSidebar" className="companion-mirrored-symbol" />
          </button>
        )}
      </span>
    </div>
  );
}
