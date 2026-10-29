import { useState } from 'react';
import { toggleWindowCollapse } from './bridge/meetingBridge';
import { useMeetingBridgeState } from './state/useMeetingBridgeState';
import WindowChrome from './components/WindowChrome';
import CompanionPane from './companion/CompanionPane';
import { CompanionLinksProvider, useCompanionLinksValue } from './companion/companionLinks';
import { companionPort } from './companion/companionTarget';
import { useCompanionGlobalSettings } from './companion/useCompanionGlobalSettings';
import { useCompanionSwitch } from './companion/useCompanionSwitch';
import { awarenessBadgeText, useCompanionAwareness } from './companion/useCompanionUnseen';
import { useMeetingCompanion } from './companion/useMeetingCompanion';
import { useCollapseShortcut } from '@shared/useCollapseShortcut';
import { useSettledExpand } from '@shared/useSettledExpand';

/** The detached Companion window: the same pane as the embedded one, bound to the live meeting through the shared bridge snapshots. */
export default function MeetingCompanionApp() {
  const state = useMeetingBridgeState();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const isContentCollapsed = useSettledExpand(isCollapsed);
  const ui = state.ui;

  const { companion, meetingId, isRecording } = useMeetingCompanion(ui);
  const companionSwitch = useCompanionSwitch(companion);
  const badge = awarenessBadgeText(useCompanionAwareness(meetingId, companion.state));
  const subtitle = [ui?.meetingName, badge].filter(Boolean).join(' · ');
  const globalSettings = useCompanionGlobalSettings(companionPort(ui));
  const links = useCompanionLinksValue({ role: 'companion', transcript: state.transcript, items: [], focusRequest: state.focusRequest });

  const handleToggleCollapse = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    toggleWindowCollapse(next);
  };

  useCollapseShortcut(handleToggleCollapse);

  return (
    <div className="basil-webkit-window-frame">
      <div className="basil-webkit-window-surface meeting-assistant-surface">
        <WindowChrome
          title="Companion"
          subtitle={subtitle !== '' ? subtitle : undefined}
          titleVariant="callout"
          featureIcon="microphone"
          isCollapsed={isCollapsed}
          onToggleCollapse={handleToggleCollapse}
          isRecording={Boolean(ui?.isRecording && !ui.isCapturePaused)}
          canCollapse
        />
        <div
          className="companion-detached-body"
          hidden={isContentCollapsed}
          aria-hidden={isContentCollapsed}
          inert={isContentCollapsed ? '' : undefined}
        >
          {!state.connected || !ui ? (
            <div className="meeting-loading-state">Connecting to Notetaker…</div>
          ) : meetingId === null ? (
            <div className="meeting-loading-state">Start or open a meeting to see its Companion.</div>
          ) : (
            <CompanionLinksProvider value={links}>
              <CompanionPane
                ui={ui}
                controller={companion}
                globalSettings={globalSettings}
                isTargetRecording={isRecording}
                variant="detached"
                toggle={isRecording ? { enabled: companion.isEnabled, busy: companionSwitch.busy, onChange: companionSwitch.change, mode: { value: companion.state.status.mode, onChange: (mode) => void companion.setMode(mode) } } : undefined}
              />
            </CompanionLinksProvider>
          )}
        </div>
      </div>
    </div>
  );
}
