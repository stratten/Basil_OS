export { applyHostFonts, applyHostTheme } from '@shared/webTheme';
import {
  DEFAULT_PROCESSING_ACCENT_HEX,
  DEFAULT_PROCESSING_BASE_HEX,
} from '../theme/generated-defaults';

export function applyProcessingDefaults(): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.style.setProperty('--processing-base', DEFAULT_PROCESSING_BASE_HEX);
  root.style.setProperty('--processing-accent', DEFAULT_PROCESSING_ACCENT_HEX);
}
