import { describe, expect, it } from 'vitest';
import { AudioSpring, BubbleAudioModel } from './audioModel';

describe('AudioSpring', () => {
  it('converges to its target under repeated stepping', () => {
    const s = new AudioSpring();
    for (let i = 0; i < 400; i++) s.update(1, 0.03);
    expect(s.currentValue).toBeCloseTo(1, 2);
  });

  it('stays bounded when speech adapts damping past the explicit-integration limit', () => {
    const s = new AudioSpring();
    const values: number[] = [];
    for (let i = 0; i < 40; i++) {
      s.adaptToAudioCharacteristics(0.05, 0.9, 'decay', 0.2, 0.03);
      s.update(1, 0.03);
      values.push(s.currentValue);
    }
    expect(s.damping * 0.03 / s.mass).toBeGreaterThan(2);
    expect(Math.max(...values.map(Math.abs))).toBeLessThan(1.5);
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

  it('moves smoothly on every 60 Hz frame through choppy speech levels', () => {
    const m = new BubbleAudioModel();
    m.setAnimationMode('audioResponsive');
    let seed = 7;
    const nextRandom = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    let previousSize = 0;
    let previousDelta = 0;
    let totalJerk = 0;
    let maxMagnitude = 0;
    const frames = 60 * 30;
    for (let frame = 0; frame < frames; frame++) {
      if (frame % 3 === 0) m.ingestAudioLevel(nextRandom() < 0.15 ? nextRandom() : nextRandom() * 0.15);
      m.advance(1 / 60);
      const delta = m.springSize - previousSize;
      totalJerk += Math.abs(delta - previousDelta);
      previousSize = m.springSize;
      previousDelta = delta;
      maxMagnitude = Math.max(maxMagnitude, Math.abs(m.springOpacity), Math.abs(m.springSize), Math.abs(m.springLevel));
    }
    expect(maxMagnitude).toBeLessThan(3);
    expect(totalJerk / frames).toBeLessThan(0.003);
  });

  it('produces the same motion at 60 Hz and 120 Hz frame rates', () => {
    const atFrameRate = (framesPerSecond: number) => {
      const m = new BubbleAudioModel();
      m.setAnimationMode('audioResponsive');
      m.ingestAudioLevel(0.1);
      m.ingestAudioLevel(0.25);
      m.ingestAudioLevel(0.4);
      for (let frame = 0; frame < framesPerSecond / 4; frame++) m.advance(1 / framesPerSecond);
      return m.springSize;
    };
    expect(atFrameRate(120)).toBeCloseTo(atFrameRate(60), 2);
  });
});
