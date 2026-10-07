import { createSwiftBridge, missingHandlerLogger } from '@shared/swiftBridge';
import type { SwiftMessage, InitMessage, ThemeConfig, FontConfig } from '../types';

declare global {
  interface Window {
    basilMiniPanel?: {
      onInit: (config: InitMessage) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
    };
  }
}

let initCallback: ((config: InitMessage) => void) | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;

// Held until React mounts and registers its handler. Without this, init
// messages dispatched before mount silently disappear.
let pendingInit: InitMessage | null = null;

export function registerInitHandler(cb: (config: InitMessage) => void) {
  initCallback = cb;
  if (pendingInit) {
    cb(pendingInit);
    pendingInit = null;
  }
}

export function registerThemeHandler(cb: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeCallback = cb;
}

window.basilMiniPanel = {
  onInit: (config: InitMessage) => {
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => themeCallback?.(theme, fonts),
};

const swiftBridge = createSwiftBridge<SwiftMessage>('miniPanelBridge', {
  onMissing: missingHandlerLogger('log', '[MiniPanelBridge] No Swift handler, message:'),
});

function postToSwift(message: SwiftMessage) {
  swiftBridge.post(message);
}

export function openAgentTaskInResultWidget(agentTaskId: string, runId: string) {
  postToSwift({ type: 'openAgentTaskInResultWidget', agentTaskId, runId });
}

export function dismissRow(runId: string) {
  postToSwift({ type: 'dismissRow', runId });
}

export function dismissPanel() {
  postToSwift({ type: 'dismissPanel' });
}

/**
 * Ask the host NSPanel to minimize into the Dock. Swift handles the
 * actual ``miniaturize(nil)`` call -- this side only forwards the
 * intent so the React UI can wire it to a header button (and any
 * future keyboard shortcut handlers that prefer to dispatch through
 * the same bridge).
 *
 * Mirrors ``dismissPanel`` shape-wise but is semantically different:
 *   * ``dismissPanel``  -> destroy / order out (panel stops existing
 *                          until the next scheduled-run event recreates
 *                          it).
 *   * ``minimizePanel`` -> shrink to the Dock; state persists; user
 *                          can click the Dock tile to restore.
 */
export function minimizePanel() {
  postToSwift({ type: 'minimizePanel' });
}

/**
 * Tell Swift the panel has no more rows to display so the host NSPanel can
 * order itself out. Sent on the trailing edge of the row count hitting zero,
 * not on every empty render, so we don't fight Swift's animation.
 */
export function notifyPanelEmpty() {
  postToSwift({ type: 'panelEmpty' });
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height });
}
