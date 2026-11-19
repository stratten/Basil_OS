import { describe, expect, it, vi } from 'vitest';
import { applyHostFonts, applyHostTheme, applyTextOnColorTokens, deriveFieldBorder, deriveSeparatorColor, deriveTextOnColor, normalizeTextScale } from './webTheme';
import { enableBackdropSurfaceFinish } from './surfaceFinish';
import { HOST_THEME_APPLIED_ATTRIBUTE, HOST_THEME_APPLIED_EVENT, isHostThemeApplied } from './hostThemeSignal';

describe('webTheme', () => {
  it('signals that the host theme is applied, and not when no theme was supplied', () => {
    document.documentElement.removeAttribute(HOST_THEME_APPLIED_ATTRIBUTE);
    const signaled = vi.fn();
    window.addEventListener(HOST_THEME_APPLIED_EVENT, signaled);

    applyHostTheme(undefined);
    expect(isHostThemeApplied()).toBe(false);
    expect(signaled).not.toHaveBeenCalled();

    applyHostTheme({ backgroundPrimary: '#ffffff' });
    expect(isHostThemeApplied()).toBe(true);
    expect(signaled).toHaveBeenCalledTimes(1);
    window.removeEventListener(HOST_THEME_APPLIED_EVENT, signaled);
  });

  it('applies every supplied theme token and resolves a light color scheme', () => {
    applyHostTheme({
      backgroundPrimary: '#ffffff',
      backgroundSecondary: '#f0f0f0',
      textPrimary: '#111318',
      successBase: '#1e8e5a',
      readyAccent: '#c8f0cb',
    });

    const style = document.documentElement.style;
    expect(style.getPropertyValue('--background-primary')).toBe('#ffffff');
    expect(style.getPropertyValue('--background-secondary')).toBe('#f0f0f0');
    expect(style.getPropertyValue('--text-primary')).toBe('#111318');
    expect(style.getPropertyValue('--success-base')).toBe('#1e8e5a');
    expect(style.getPropertyValue('--ready-accent')).toBe('#c8f0cb');
    expect(style.getPropertyValue('color-scheme')).toBe('light');
  });

  it('resolves a dark color scheme from hexadecimal and RGB background colors', () => {
    applyHostTheme({ backgroundPrimary: '#101820' });
    expect(document.documentElement.style.getPropertyValue('color-scheme')).toBe('dark');

    applyHostTheme({ backgroundPrimary: 'rgb(240, 240, 240)' });
    expect(document.documentElement.style.getPropertyValue('color-scheme')).toBe('light');
  });

  it('leaves the active color scheme unchanged for an unsupported color format', () => {
    document.documentElement.style.setProperty('color-scheme', 'dark');
    applyHostTheme({ backgroundPrimary: 'var(--system-background)' });
    expect(document.documentElement.style.getPropertyValue('color-scheme')).toBe('dark');
  });

  it('derives the divider color from the secondary color and ignores the host separator color', () => {
    applyHostTheme({ secondary: '#2a5db0', separatorColor: 'rgba(0, 0, 0, 0.35)' });
    expect(document.documentElement.style.getPropertyValue('--separator-color')).toBe(
      deriveSeparatorColor('#2a5db0'),
    );
    expect(deriveSeparatorColor('#2a5db0')).toBe('color-mix(in srgb, #2a5db0 18%, transparent)');
  });

  it('derives the input outline from the secondary color and ignores the opaque host field border', () => {
    applyHostTheme({ secondary: '#2a5db0', fieldBorder: '#2a5db0' });
    expect(document.documentElement.style.getPropertyValue('--field-border')).toBe(deriveFieldBorder('#2a5db0'));
    expect(deriveFieldBorder('#2a5db0')).toBe('color-mix(in srgb, #2a5db0 20%, transparent)');
    expect(deriveFieldBorder()).toBe('color-mix(in srgb, var(--secondary) 20%, transparent)');
  });

  it('falls back to the applied secondary token when the theme carries no secondary color', () => {
    expect(deriveSeparatorColor()).toBe('color-mix(in srgb, var(--secondary) 18%, transparent)');
    expect(deriveSeparatorColor('  ')).toBe('color-mix(in srgb, var(--secondary) 18%, transparent)');
  });

  it('maps regular, medium, semibold, and bold font tokens', () => {
    applyHostFonts({
      fontFamily: 'Helvetica Neue',
      fontFamilyMedium: 'HelveticaNeue-Medium',
      fontFamilyBold: 'HelveticaNeue-Bold',
    });

    const style = document.documentElement.style;
    expect(style.getPropertyValue('--font-family')).toBe('Helvetica Neue');
    expect(style.getPropertyValue('--font-family-light')).toBe('Helvetica Neue');
    expect(style.getPropertyValue('--font-family-medium')).toBe('HelveticaNeue-Medium');
    expect(style.getPropertyValue('--font-family-semibold')).toBe('HelveticaNeue-Bold');
    expect(style.getPropertyValue('--font-family-bold')).toBe('HelveticaNeue-Bold');
  });

  it('defaults surface finish to flat and updates it without duplicating its style element', () => {
    applyHostTheme({ backgroundPrimary: '#ffffff' });
    expect(document.documentElement.dataset.surfaceFinish).toBe('flat');
    expect(document.getElementById('basil-surface-finish-style')).not.toBeNull();
    const styleCount = document.querySelectorAll('#basil-surface-finish-style').length;

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal' });
    expect(document.documentElement.dataset.surfaceFinish).toBe('metal');
    expect(document.querySelectorAll('#basil-surface-finish-style').length).toBe(styleCount);
  });

  it('treats unknown surface finishes as flat', () => {
    applyHostTheme({ backgroundPrimary: '#ffffff', surfaceFinish: 'chrome' });

    expect(document.documentElement.dataset.surfaceFinish).toBe('flat');
  });

  it('targets the rounded window surface instead of the document viewport', () => {
    document.body.innerHTML = '<div id="root"><main class="basil-webkit-window-surface"></main></div>';

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal' });

    expect(
      document.querySelector('.basil-webkit-window-surface')?.hasAttribute('data-basil-surface-finish-target'),
    ).toBe(true);
    expect(document.getElementById('root')?.hasAttribute('data-basil-surface-finish-target')).toBe(false);
    expect(document.getElementById('basil-surface-finish-style')?.textContent).not.toContain('body::after');
  });

  it('targets the window frame above opaque child surfaces when one is available', () => {
    document.body.innerHTML = '<div id="root"><section class="basil-webkit-window-frame"><main class="basil-webkit-window-surface"></main></section></div>';

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal' });

    expect(
      document.querySelector('.basil-webkit-window-frame')?.hasAttribute('data-basil-surface-finish-target'),
    ).toBe(true);
    expect(
      document.querySelector('.basil-webkit-window-surface')?.hasAttribute('data-basil-surface-finish-target'),
    ).toBe(false);
    expect(document.getElementById('basil-surface-finish-style')?.textContent).toContain(
      '.basil-surface-finish-overlay',
    );
    expect(document.querySelector('.basil-webkit-window-frame > .basil-surface-finish-overlay')).not.toBeNull();

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'flat' });
    expect(document.querySelector('.basil-surface-finish-overlay')).toBeNull();
  });

  it('renders the backdrop finish as metal in windows that have not opted in', () => {
    enableBackdropSurfaceFinish(false);
    document.body.innerHTML = '<div id="root"><section class="basil-webkit-window-frame"><main class="basil-webkit-window-surface"></main></section></div>';

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal_backdrop' });

    expect(document.documentElement.dataset.surfaceFinish).toBe('metal');
    expect(document.querySelector('.basil-webkit-window-frame > .basil-surface-finish-overlay')).not.toBeNull();
  });

  it('places the backdrop finish behind window content once the window opts in', () => {
    enableBackdropSurfaceFinish();
    document.body.innerHTML = '<div id="root"><section class="basil-webkit-window-frame"><main class="basil-webkit-window-surface"></main></section></div>';

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal_backdrop' });

    expect(document.documentElement.dataset.surfaceFinish).toBe('metal_backdrop');
    expect(document.querySelector('.basil-webkit-window-frame > .basil-surface-finish-overlay')).not.toBeNull();
    const css = document.getElementById('basil-surface-finish-style')?.textContent ?? '';
    expect(css).toContain('html[data-surface-finish="metal_backdrop"] .basil-webkit-window-frame > .basil-surface-finish-overlay {\n  z-index: 1;');
    expect(css).toContain('html[data-surface-finish="metal_backdrop"] .basil-webkit-window-frame > .basil-webkit-window-surface {\n  z-index: 2;');
    expect(css).toContain('html[data-surface-finish="metal_backdrop"] .basil-webkit-window-frame::before {\n  z-index: 3;');

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal' });
    expect(document.documentElement.dataset.surfaceFinish).toBe('metal');
    enableBackdropSurfaceFinish(false);
  });

  it('retargets the finish when the rounded window surface mounts after initialization', async () => {
    document.body.innerHTML = '<div id="root"></div>';

    applyHostTheme({ backgroundPrimary: '#101820', surfaceFinish: 'metal' });
    const root = document.getElementById('root')!;
    expect(root.hasAttribute('data-basil-surface-finish-target')).toBe(true);

    root.innerHTML = '<main class="basil-webkit-window-surface"></main>';
    await Promise.resolve();

    expect(
      document.querySelector('.basil-webkit-window-surface')?.hasAttribute('data-basil-surface-finish-target'),
    ).toBe(true);
    expect(root.hasAttribute('data-basil-surface-finish-target')).toBe(false);
  });

  describe('text scale', () => {
    const readScale = () => document.documentElement.style.getPropertyValue('--text-scale');

    it('sets --text-scale from the published value', () => {
      applyHostTheme({ textScale: 1.25 });
      expect(readScale()).toBe('1.25');
      applyHostTheme({ textScale: 0.9 });
      expect(readScale()).toBe('0.9');
    });

    it('clamps a value outside the offered range', () => {
      applyHostTheme({ textScale: 9 });
      expect(readScale()).toBe('1.4');
      applyHostTheme({ textScale: 0.1 });
      expect(readScale()).toBe('0.9');
    });

    it('keeps the current size when the theme carries no usable value', () => {
      applyHostTheme({ textScale: 1.1 });
      applyHostTheme({ backgroundPrimary: '#ffffff' });
      expect(readScale()).toBe('1.1');
      applyHostTheme({ textScale: Number.NaN });
      expect(readScale()).toBe('1.1');
      applyHostTheme({ textScale: '1.4' as unknown as number });
      expect(readScale()).toBe('1.1');
    });

    it('does not treat textScale as a color token', () => {
      applyHostTheme({ textScale: 1.25 });
      expect(document.documentElement.style.getPropertyValue('--text-scale-color')).toBe('');
    });

    it('normalizes only finite numbers', () => {
      expect(normalizeTextScale(1)).toBe(1);
      expect(normalizeTextScale(Number.POSITIVE_INFINITY)).toBeUndefined();
      expect(normalizeTextScale(undefined)).toBeUndefined();
      expect(normalizeTextScale(null)).toBeUndefined();
    });
  });

  describe('text on a solid fill', () => {
    const readToken = (name: string) => document.documentElement.style.getPropertyValue(name);

    it('keeps white on a fill where white stays legible and turns black where it does not', () => {
      expect(deriveTextOnColor('#33559b')).toBe('#ffffff');
      expect(deriveTextOnColor('rgb(0, 48, 135)')).toBe('#ffffff');
      expect(deriveTextOnColor('#ffd60a')).toBe('#000000');
      expect(deriveTextOnColor('rgb(240, 240, 240)')).toBe('#000000');
    });

    it('returns undefined for a missing or unparseable fill', () => {
      expect(deriveTextOnColor(undefined)).toBeUndefined();
      expect(deriveTextOnColor('')).toBeUndefined();
      expect(deriveTextOnColor('var(--primary)')).toBeUndefined();
      expect(deriveTextOnColor('color-mix(in srgb, red 50%, blue)')).toBeUndefined();
    });

    it('publishes a label color for every supplied fill when the host theme is applied', () => {
      applyHostTheme({
        primary: '#33559b',
        secondary: '#ffd60a',
        successBase: '#1e8e5a',
        warningBase: '#f5a623',
        errorBase: '#b42318',
        processingBase: '#5856d6',
        recordingBase: '#8b0000',
      });
      expect(readToken('--text-on-primary')).toBe('#ffffff');
      expect(readToken('--text-on-secondary')).toBe('#000000');
      expect(readToken('--text-on-success')).toBe('#ffffff');
      expect(readToken('--text-on-warning')).toBe('#000000');
      expect(readToken('--text-on-error')).toBe('#ffffff');
      expect(readToken('--text-on-processing')).toBe('#ffffff');
      expect(readToken('--text-on-recording')).toBe('#ffffff');
    });

    it('derives a missing fill from the fill token already applied to the page', () => {
      document.documentElement.style.setProperty('--error-base', '#ffe08a');
      document.documentElement.style.removeProperty('--text-on-error');
      applyTextOnColorTokens({ primary: '#33559b' });
      expect(readToken('--text-on-error')).toBe('#000000');
      expect(readToken('--text-on-primary')).toBe('#ffffff');
    });

    it('leaves a label color unchanged when its fill cannot be resolved', () => {
      document.documentElement.style.setProperty('--text-on-warning', '#123456');
      document.documentElement.style.removeProperty('--warning-base');
      applyTextOnColorTokens({});
      expect(readToken('--text-on-warning')).toBe('#123456');
    });
  });
});
