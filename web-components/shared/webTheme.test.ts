import { describe, expect, it } from 'vitest';
import { applyHostFonts, applyHostTheme } from './webTheme';

describe('webTheme', () => {
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
});
