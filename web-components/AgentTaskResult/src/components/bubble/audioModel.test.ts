import { describe, expect, it } from 'vitest';
import { AudioSpring, BubbleAudioModel } from './audioModel';

describe('AudioSpring', () => {
  it('converges to its target under repeated stepping', () => {
    const s = new AudioSpring();
    for (let i = 0; i < 400; i++) s.update(1, 0.03);
    expect(s.currentValue).toBeCloseTo(1, 2);
  });

  it('clamps adapted coefficients into native bounds', () => {
    const s = new AudioSpring();
    for (let i = 0; i < 50; i++) s.adaptToAudioCharacteristics(1, 1, 'transient', 1);
    expect(s.stiffness).toBeLessThanOrEqual(800);
    expect(s.stiffness).toBeGreaterThanOrEqual(50);
    expect(s.damping).toBeLessThanOrEqual(100);
    expect(s.mass).toBeLessThanOrEqual(5);
  });
});

describe('BubbleAudioModel', () => {
  it('rate-limits a large level jump via advanced smoothing', () => {
    const m = new BubbleAudioModel();
    m.ingestAudioLevel(0);
    m.ingestAudioLevel(1);
    expect(m.currentLevel).toBeLessThan(0.3);
  });

  it('starts a mode transition and completes it after advancing', () => {
    const m = new BubbleAudioModel();
    m.setAnimationMode('processing');
    expect(m.modeTransitionProgress).toBe(0);
    m.advance(1.0);
    expect(m.modeTransitionProgress).toBe(1);
    expect(m.currentAnimationMode).toBe('processing');
  });

  it('drives spring level toward a sustained audio level', () => {
    const m = new BubbleAudioModel();
    for (let i = 0; i < 100; i++) {
      m.ingestAudioLevel(0.8);
      m.advance(0.03);
    }
    expect(m.springLevel).toBeGreaterThan(0.3);
  });
});
