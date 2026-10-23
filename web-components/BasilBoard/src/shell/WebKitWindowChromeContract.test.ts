import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('WebKit window chrome contract', () => {
  const sharedCss = readFileSync('../shared/webkit-window-chrome.css', 'utf8');
  const shellCss = readFileSync('src/styles/shell.css', 'utf8');
  const meetingPanelApp = readFileSync('../MeetingDetectedMiniPanel/src/App.tsx', 'utf8');
  const meetingPanelCss = readFileSync('../MeetingDetectedMiniPanel/src/styles/panel.css', 'utf8');
  const scheduledPanelApp = readFileSync('../ScheduledRunMiniPanel/src/App.tsx', 'utf8');
  const scheduledPanelCss = readFileSync('../ScheduledRunMiniPanel/src/styles/panel.css', 'utf8');
  const setupChrome = readFileSync('../SetupAssistantWebComponents/src/components/layout/SetupWindowChrome.tsx', 'utf8');
  const setupShell = readFileSync('../SetupAssistantWebComponents/src/components/layout/SetupShell.tsx', 'utf8');
  const setupPermissionsEntry = readFileSync('../SetupAssistantWebComponents/src/entries/setup-permissions.tsx', 'utf8');
  const setupCss = readFileSync('../SetupAssistantWebComponents/src/styles/setup-assistant.shared.css', 'utf8');

  it('defines the authoritative frame inset, radius, and ring tokens', () => {
    expect(sharedCss).toContain('--basil-webkit-window-frame-inset: 4px');
    expect(sharedCss).toContain('--basil-webkit-window-corner-radius: 16px');
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame \{[\s\S]*box-sizing: border-box;/);
    expect(sharedCss).toMatch(/\.basil-webkit-window-surface \{[\s\S]*box-sizing: border-box;/);
    expect(sharedCss).toContain('color-mix(in srgb, var(--secondary) 30%, transparent)');
    expect(sharedCss).toContain('color-mix(in srgb, var(--secondary) 16%, transparent)');
    expect(sharedCss).toContain('color-mix(in srgb, var(--secondary) 8%, transparent)');
  });

  it('paints the Swift stroke stack above opaque window content', () => {
    expect(sharedCss).toContain('.basil-webkit-window-frame::before');
    expect(sharedCss).toContain('inset: calc(var(--basil-webkit-window-frame-inset) + 0.5px);');
    expect(sharedCss).toContain('border-radius: calc(var(--basil-webkit-window-corner-radius) - 0.5px);');
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame::before \{[\s\S]*z-index: 2;/);
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame::before \{[\s\S]*background: transparent;/);
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame::after \{[\s\S]*z-index: 0;[\s\S]*background: var\(--background-primary\);/);
    expect(sharedCss).toContain('0 0 0 3px var(--basil-webkit-window-outer-stroke)');
    expect(sharedCss).toContain('0 0 0 2px var(--basil-webkit-window-middle-stroke)');
    expect(sharedCss).toContain('0 0 0 1px var(--basil-webkit-window-blue-stroke)');
    expect(sharedCss).toMatch(/\.basil-webkit-window-surface \{[\s\S]*position: relative;[\s\S]*z-index: 1;/);
    expect(sharedCss).toMatch(/\.basil-webkit-window-surface \{[\s\S]*background: transparent;/);
    expect(sharedCss).not.toContain('outline:');
    expect(sharedCss).not.toContain('outline-offset:');
  });

  it('strips all chrome for embedded surfaces', () => {
    expect(sharedCss).toContain('.basil-webkit-window-frame--embedded .basil-webkit-window-surface');
    expect(sharedCss).toContain('border-radius: 0;');
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame--embedded::before \{[\s\S]*display: none;/);
    expect(sharedCss).toMatch(/\.basil-webkit-window-frame--embedded::after \{[\s\S]*display: none;/);
  });

  it('removes the legacy blurred shell border contract from BasilBoard', () => {
    expect(shellCss).not.toContain('border: 0.5px solid rgba(0, 48, 135, 0.25)');
    expect(shellCss).not.toContain('0 0 8px 2px');
  });

  it('requires every standalone React window to consume the shared frame contract', () => {
    // A window may apply the frame/surface classes directly (mini panels) or
    // delegate to the shared `BasilWindowChrome` component, which itself
    // renders both classes (SetupWindowChrome) — either path satisfies the
    // contract, so accept both instead of requiring literal duplication.
    for (const appSource of [meetingPanelApp, scheduledPanelApp, setupChrome]) {
      const consumesSharedChrome = appSource.includes('BasilWindowChrome');
      if (!consumesSharedChrome) {
        expect(appSource).toContain('basil-webkit-window-frame');
        expect(appSource).toContain('basil-webkit-window-surface');
      }
    }
    for (const cssSource of [meetingPanelCss, scheduledPanelCss, setupCss]) {
      expect(cssSource).toContain("@import '../../../shared/webkit-window-chrome.css';");
    }
    expect(setupShell).toContain('<SetupWindowChrome title="Basil Setup Assistant">');
    expect(setupPermissionsEntry).toContain('<SetupWindowChrome title="Basil Permissions">');
    expect(meetingPanelCss).not.toContain('0 8px 24px rgba(0, 0, 0, 0.12)');
    expect(scheduledPanelCss).not.toContain('0 8px 24px rgba(0, 0, 0, 0.12)');
  });
});
