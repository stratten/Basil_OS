import type { AssistantSessionThemePayload } from '../bridge/types';
import { applyHostFonts, applyHostTheme } from '@shared/webTheme';

export function applyAssistantSessionTheme(theme: AssistantSessionThemePayload): void {
  applyHostTheme({
    ...theme,
    separatorColor: `color-mix(in srgb, ${theme.secondary} 18%, transparent)`,
  });
  applyHostFonts({
    fontFamily: theme.preferredFontName,
    fontFamilyMedium: theme.preferredFontName,
    fontFamilyBold: theme.preferredFontName,
  });
}
