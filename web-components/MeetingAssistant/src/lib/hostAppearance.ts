import type { MeetingFontPayloadDTO, MeetingThemePayloadDTO } from '../bridge/types';
import { applyHostFonts, applyHostTheme } from '@shared/webTheme';

export function applyMeetingHostTheme(theme: MeetingThemePayloadDTO | null): void {
  applyHostTheme(theme ?? undefined);
}

export function applyMeetingHostFonts(fonts: MeetingFontPayloadDTO | null): void {
  applyHostFonts(fonts ?? undefined);
}
