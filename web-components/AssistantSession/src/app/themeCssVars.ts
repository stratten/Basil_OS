import type { AssistantSessionThemePayload } from '../bridge/types';
import { applyHostFonts, applyHostTheme } from '@shared/theme/webTheme';

export function applyAssistantSessionTheme(theme: AssistantSessionThemePayload): void {
  applyHostTheme(theme);
  applyHostFonts({
    fontFamily: theme.preferredFontName,
    fontFamilyMedium: theme.preferredFontName,
    fontFamilyBold: theme.preferredFontName,
  });
}
