import type { FontConfig, InitMessage, MeetingInfo, SwiftMessage, ThemeConfig } from '../types';

declare global {
  interface Window {
    webkit?: {
      messageHandlers: {
        meetingDetectedPanelBridge: {
          postMessage: (message: SwiftMessage) => void;
        };
      };
    };
    basilMeetingDetectedPanel?: {
      onInit: (config: InitMessage) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
      onMeetingChanged: (meeting: MeetingInfo) => void;
    };
  }
}

let initCallback: ((config: InitMessage) => void) | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;
let meetingCallback: ((meeting: MeetingInfo) => void) | null = null;

let pendingInit: InitMessage | null = null;
let pendingMeeting: MeetingInfo | null = null;

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

export function registerMeetingHandler(cb: (meeting: MeetingInfo) => void) {
  meetingCallback = cb;
  if (pendingMeeting) {
    cb(pendingMeeting);
    pendingMeeting = null;
  }
}

window.basilMeetingDetectedPanel = {
  onInit: (config: InitMessage) => {
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => themeCallback?.(theme, fonts),
  onMeetingChanged: (meeting: MeetingInfo) => {
    if (meetingCallback) {
      meetingCallback(meeting);
    } else {
      pendingMeeting = meeting;
    }
  },
};

function postToSwift(message: SwiftMessage) {
  if (window.webkit?.messageHandlers.meetingDetectedPanelBridge) {
    window.webkit.messageHandlers.meetingDetectedPanelBridge.postMessage(message);
  } else {
    console.log('[MeetingDetectedPanelBridge] No Swift handler, message:', message);
  }
}

export function startMeeting() {
  postToSwift({ type: 'startMeeting' });
}

export function notifyReady() {
  postToSwift({ type: 'reactReady' });
}

export function dismissMeeting() {
  postToSwift({ type: 'dismissMeeting' });
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height });
}
