import { describe, expect, it } from 'vitest';
import { applyReadableTextGuard, readableTextOverride } from './readableText';

describe('readableTextOverride', () => {
  it('replaces dark text on a navy surface with white', () => {
    expect(readableTextOverride('#0B1F3A', '#1a1a2e')?.textPrimary).toBe('#ffffff');
  });

  it('replaces light text on a white surface with black', () => {
    expect(readableTextOverride('#ffffff', '#f0f0f0')?.textPrimary).toBe('#000000');
  });

  it('leaves readable host colors alone', () => {
    expect(readableTextOverride('#0B1F3A', '#ffffff')).toBeNull();
    expect(readableTextOverride('#ffffff', '#111827')).toBeNull();
  });

  it('ignores values that are not plain hex colors', () => {
    expect(readableTextOverride('rgba(0,0,0,0.5)', '#000000')).toBeNull();
    expect(readableTextOverride(undefined, undefined)).toBeNull();
  });

  it('writes the override onto the root only when needed', () => {
    const written = new Map<string, string>();
    const root = { style: { setProperty: (name: string, value: string) => void written.set(name, value) } };
    applyReadableTextGuard({ backgroundPrimary: '#0B1F3A', textPrimary: '#ffffff' }, root);
    expect(written.size).toBe(0);
    applyReadableTextGuard({ backgroundPrimary: '#0B1F3A', textPrimary: '#1a1a2e' }, root);
    expect(written.get('--text-primary')).toBe('#ffffff');
    expect(written.get('--text-secondary')).toContain('255, 255, 255');
  });
});
