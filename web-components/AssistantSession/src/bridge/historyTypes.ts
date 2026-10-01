// web-components/AssistantSession/src/bridge/historyTypes.ts

export interface AssistantOutputHistoryInitPayload {
  baseUrl: string;
  anchoredToWidget: boolean;
  theme: import('./types').AssistantSessionThemePayload;
}

export type HistoryRefinementInput = 'voice' | 'typed';

export type AssistantOutputHistoryBridgeEvent =
  | ({ type: 'init' } & AssistantOutputHistoryInitPayload)
  | ({ type: 'themeChanged' } & import('./types').AssistantSessionThemePayload)
  | { type: 'historyUpdated' }
  | { type: 'historyActionError'; message: string };

export type AssistantOutputHistoryBridgeIntent =
  | { type: 'historyWidgetReady' }
  | { type: 'closeWindow' }
  | { type: 'minimizeWindow' }
  | { type: 'toggleChromeCollapse'; collapsed: boolean }
  | { type: 'refineFromHistory'; assistantOutputId: number; input: HistoryRefinementInput }
  | { type: 'copyHistoryRichText'; content: string }
  | { type: 'copyHistoryMarkdown'; content: string }
  | { type: 'openHistoryExternalUrl'; url: string };
