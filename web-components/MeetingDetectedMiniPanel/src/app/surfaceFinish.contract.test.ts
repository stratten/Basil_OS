import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('Meeting detected panel surface finish', () => {
  it('opts the window into the background-only metallic finish before rendering', () => {
    const entry = readFileSync('src/main.tsx', 'utf8');
    expect(entry).toContain("import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'");
    expect(entry.indexOf('enableBackdropSurfaceFinish()')).toBeGreaterThan(-1);
    expect(entry.indexOf('enableBackdropSurfaceFinish()')).toBeLessThan(entry.indexOf('createRoot('));
  });
});
