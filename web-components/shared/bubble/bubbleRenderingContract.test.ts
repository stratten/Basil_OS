import { describe, expect, it } from 'vitest';
import { BubbleAudioModel } from './audioModel';
import { computeCapsules } from './bubbleGeometry';
import { FRAGMENT_SRC } from './bubbleShaders';

function settledModel(mode: 'ambient' | 'processing'): BubbleAudioModel {
  const model = new BubbleAudioModel();
  model.setAnimationMode(mode);
  model.advance(1);
  return model;
}

describe('bubble rendering contract', () => {
  it('uses one normalized rotational Gaussian blur kernel per capsule', () => {
    expect(FRAGMENT_SRC).toContain('float blurredCapsuleCoverage(vec2 point, float halfSeg, float radius, float blurRadius)');
    expect(FRAGMENT_SRC).toContain('float sigma = max(blurRadius, 0.5);');
    expect(FRAGMENT_SRC).toContain('for (int sampleIndex = 0; sampleIndex < 32; sampleIndex++)');
    expect(FRAGMENT_SRC).toContain('float sampleAngle = float(sampleIndex) * 2.39996322973;');
    expect(FRAGMENT_SRC).toContain('return coverage / 32.0;');
    expect(FRAGMENT_SRC).not.toContain('for (int sampleX');
    expect(FRAGMENT_SRC).not.toContain('for (int sampleY');
    expect(FRAGMENT_SRC).toContain('float highlightLevel = max(normalizedHighlight.r');
    expect(FRAGMENT_SRC).toContain('float compressedLevel = 0.55 + 0.17 * (1.0 - exp(');
    expect(FRAGMENT_SRC).not.toContain('result = min(result, ceiling);');
    expect(FRAGMENT_SRC).not.toContain('channelFloor');
    expect(FRAGMENT_SRC).toContain('float hueWeight = hue < 180.0 ? 1.0 - smoothstep(60.0, 80.0, hue) : smoothstep(320.0, 340.0, hue);');
    expect(FRAGMENT_SRC).toContain('vec3 whiteHighlight = softKnee(max(uncompressed - uBaseColor, vec3(0.0)) / whiteHeadroom, 0.65, 0.92);');
    expect(FRAGMENT_SRC).toContain('result = mix(result, uBaseColor + whiteHeadroom * whiteHighlight, warmWeight);');
    expect(FRAGMENT_SRC).not.toContain('ETHEREAL_MIX');
    expect(FRAGMENT_SRC).not.toContain('filledCoverage');
    expect(FRAGMENT_SRC).toContain('gl_FragColor = vec4(result * circleCoverage, circleCoverage);');
  });

  it('keeps ambient capsule bodies and center offsets within native proportions', () => {
    const capsules = computeCapsules(100, 1, 2.75, settledModel('ambient'));

    for (let index = 0; index < capsules.count; index += 1) {
      const height = capsules.halfSeg[index] * 2 + capsules.radius[index] * 2;
      const radialDistance = Math.hypot(capsules.center[index * 2], capsules.center[index * 2 + 1]);

      expect(height).toBeGreaterThanOrEqual(18);
      expect(height).toBeLessThanOrEqual(36);
      expect(radialDistance).toBeGreaterThanOrEqual(5);
      expect(radialDistance).toBeLessThanOrEqual(15);
      expect(capsules.blur[index]).toBeGreaterThanOrEqual(2);
      expect(capsules.blur[index]).toBeLessThanOrEqual(9.1);
    }
  });

  it('keeps zero-energy processing centers on the native 5–15% radial trajectory', () => {
    const processingModel = settledModel('processing');
    const radialDistances: number[] = [];

    for (let time = 0; time <= 40; time += 0.05) {
      const capsules = computeCapsules(100, 1, time, processingModel);
      for (let index = 0; index < capsules.count; index += 1) {
        radialDistances.push(Math.hypot(capsules.center[index * 2], capsules.center[index * 2 + 1]));
      }
    }

    expect(Math.min(...radialDistances)).toBeGreaterThanOrEqual(5);
    expect(Math.min(...radialDistances)).toBeLessThan(5.1);
    expect(Math.max(...radialDistances)).toBeGreaterThan(14.9);
    expect(Math.max(...radialDistances)).toBeLessThanOrEqual(15);
  });

  it('keeps ambient and processing opacity within the controlled anti-washout envelope', () => {
    const ambientModel = settledModel('ambient');
    const processingModel = settledModel('processing');
    const ambientOpacities: number[] = [];
    const processingOpacities: number[] = [];

    for (let time = 0; time <= 40; time += 0.05) {
      ambientOpacities.push(...computeCapsules(44, 1, time, ambientModel).opacity);
      processingOpacities.push(...computeCapsules(44, 1, time, processingModel).opacity);
    }

    expect(Math.min(...ambientOpacities)).toBeGreaterThanOrEqual(0.049);
    expect(Math.max(...ambientOpacities)).toBeLessThanOrEqual(0.49);
    expect(Math.min(...processingOpacities)).toBeGreaterThanOrEqual(0.049);
    expect(Math.max(...processingOpacities)).toBeLessThanOrEqual(0.49);
    expect(Math.max(...ambientOpacities)).toBeGreaterThan(0.48);
    expect(Math.max(...processingOpacities)).toBeGreaterThan(0.48);
  });
});
