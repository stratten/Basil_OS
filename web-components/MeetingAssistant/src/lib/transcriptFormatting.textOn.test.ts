import { describe, expect, it } from 'vitest';
import { transcriptTextOnColor } from './transcriptFormatting';

describe('transcriptTextOnColor', () => {
  it('maps a theme fill to its matching label token', () => {
    expect(transcriptTextOnColor('var(--primary)')).toBe('var(--text-on-primary)');
    expect(transcriptTextOnColor('var(--secondary)')).toBe('var(--text-on-secondary)');
    expect(transcriptTextOnColor('var(--success-base)')).toBe('var(--text-on-success)');
  });

  it('derives a label color for a literal fill', () => {
    expect(transcriptTextOnColor('#6D4C41')).toBe('#ffffff');
    expect(transcriptTextOnColor('#FFE08A')).toBe('#000000');
  });

  it('leaves the stylesheet fallback in place when there is no fill or it cannot be resolved', () => {
    expect(transcriptTextOnColor(null)).toBeUndefined();
    expect(transcriptTextOnColor('var(--unknown)')).toBeUndefined();
  });
});
