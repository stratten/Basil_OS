// web-components/TranscriptionWidget/src/app/themeCssVars.ts

import type { TranscriptionThemePayload } from '../bridge/types';
import { applyHostFonts, applyHostTheme } from '@shared/webTheme';

export function applyTranscriptionTheme(theme: TranscriptionThemePayload): void {
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
