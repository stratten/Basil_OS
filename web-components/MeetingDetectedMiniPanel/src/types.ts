import type { ThemeConfig as SharedThemeConfig } from '@shared/webTheme';

export type ThemeConfig = SharedThemeConfig & {
  backgroundPrimary: string;
  primary: string;
  processingRgb?: string;
  secondary: string;
  textPrimary: string;
};

export interface FontConfig {
  fontFamily: string;
  fontFamilyMedium: string;
  fontFamilyBold: string;
}

export interface InitMessage {
  theme: ThemeConfig;
  fonts: FontConfig;
}

export interface MeetingInfo {
  appName: string;
  bundleID: string;
  mode: string;
  displayTitle: string;
  calendarTitle: string;
  calendarName: string;
  calendarAttendees: string[];
  calendarJoinURL: string;
  calendarHasCallInfo: boolean;
  calendarEventID: string;
  canJoinMeeting: boolean;
}

export type SwiftMessage =
  | { type: 'reactReady' }
  | { type: 'startMeeting' }
  | { type: 'dismissMeeting' }
  | { type: 'requestResize'; width: number; height: number };
