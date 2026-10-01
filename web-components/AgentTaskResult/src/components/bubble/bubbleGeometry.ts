import type { BubbleAnimationMode, BubbleAudioModel } from './audioModel';

const NUM_CAPSULES = 8;

export interface CapsuleUniforms {
  center: Float32Array;   // 16: x,y device px offset from bubble center (y-down, Swift convention)
  halfSeg: Float32Array;  // 8: half straight-segment length device px
  radius: Float32Array;   // 8: capsule radius device px
  rot: Float32Array;      // 8: radians
  opacity: Float32Array;  // 8
  blur: Float32Array;     // 8: edge-softness device px
  count: number;
}

function lerp(a: number, b: number, t: number): number {
  return a * (1 - t) + b * t;
}

function blended(
  m: BubbleAudioModel,
  fn: (mode: BubbleAnimationMode) => number,
): number {
  if (m.modeTransitionProgress >= 1) return fn(m.currentAnimationMode);
  return lerp(fn(m.currentAnimationMode), fn(m.targetMode), m.modeTransitionProgress);
}

function opacityFor(mode: BubbleAnimationMode, i: number, t: number, base: number, m: BubbleAudioModel): number {
  switch (mode) {
    case 'audioResponsive':
      return Math.pow(Math.min(1.0, base + m.springOpacity * 1.44 * 0.96), 0.4);
    case 'processing': {
      const phase = t * 1.5 + i * 0.8;
      // Keep processing below the native ambient range so pale purple and amber accents do not wash out.
      return Math.min(1.0, base * 0.25 + Math.pow((Math.sin(phase) + 1) / 2, 0.5) * 0.35);
    }
    case 'ambient': {
      const phase = t * 0.3 + i * 0.5;
      // Keep the native phase wave while lowering its opacity envelope so the normalized blur preserves distinct capsules.
      return Math.min(1.0, base * 0.25 + Math.pow((Math.sin(phase) + 1) / 2, 0.6) * 0.35);
    }
  }
}

function heightStretchFor(mode: BubbleAnimationMode, i: number, t: number, size: number, m: BubbleAudioModel): number {
  switch (mode) {
    case 'audioResponsive':
      return (m.springSize + m.bassLevel * 0.48 + m.trebleLevel * 0.36) * size * 0.42;
    case 'processing': {
      const phase = t * 1.2 + i * 0.6;
      return ((Math.sin(phase) + 1) / 2) * size * 0.25;
    }
    case 'ambient': {
      const phase = t * 0.4 + i * 0.3;
      return ((Math.sin(phase) + 1) / 2) * size * 0.1;
    }
  }
}

function blurFor(mode: BubbleAnimationMode, i: number, t: number, m: BubbleAudioModel): number {
  switch (mode) {
    case 'audioResponsive':
      return m.springOpacity * 2.4;
    case 'processing': {
      const phase = t * 1.0 + i * 0.5;
      return ((Math.sin(phase) + 1) / 2) * 3;
    }
    case 'ambient': {
      const phase = t * 0.2 + i * 0.4;
      return ((Math.sin(phase) + 1) / 2) * 1.5;
    }
  }
}

function scaleFor(mode: BubbleAnimationMode, t: number, m: BubbleAudioModel): number {
  switch (mode) {
    case 'audioResponsive': {
      const baseScale = 1.0 + Math.sin(t * 0.5) * 0.02;
      const springScale = m.springSize * 0.144;
      const velocityScale = Math.abs(m.audioVelocity) * 0.048;
      let eventScale = 0;
      switch (m.audioEventType) {
        case 'transient': eventScale = 0.048; break;
        case 'sustained': eventScale = 0.024; break;
        case 'attack': eventScale = 0.036; break;
        case 'decay': eventScale = 0.012; break;
        case 'none': eventScale = 0; break;
      }
      return baseScale + springScale + velocityScale + eventScale;
    }
    case 'processing':
      return 1.0 + Math.sin(t * 0.8) * 0.04;
    case 'ambient':
      return 1.0 + Math.sin(t * 0.3) * 0.01;
  }
}

function capsuleHeight(i: number, t: number, size: number, m: BubbleAudioModel): number {
  // Match the native capsule body; continuous shader blur supplies the surrounding volume.
  const baseHeight = size * 0.18;
  const primaryWave = (Math.sin(t * 2.0 + i * 0.7) + 1) / 2;
  const secondaryWave = (Math.cos(t * 0.8 + i * 0.3) + 1) / 2;
  const waveStretch = primaryWave * 0.7 + secondaryWave * 0.3;
  return baseHeight + waveStretch * size * 0.08 + blended(m, (mode) => heightStretchFor(mode, i, t, size, m));
}

function capsuleRotationDeg(i: number, t: number): number {
  const continuous = t * 5.0;
  const primary = Math.sin(t * 2.0 + i * 0.7) * 30.0;
  const secondary = Math.cos(t * 1.2 + i * 0.5) * 15.0;
  return continuous + primary + secondary + i * 10;
}

function capsuleRadialDistance(i: number, t: number, size: number, m: BubbleAudioModel): number {
  // Match the native center trajectory in every animation mode.
  const baseDistance = size * 0.05;
  const primaryWave = (Math.sin(t * 2.0 + i * 0.7) + 1) / 2;
  const secondaryWave = (Math.cos(t * 0.9 + i * 0.4) + 1) / 2;
  const combinedWave = primaryWave * 0.6 + secondaryWave * 0.4;
  const springInfluence = m.springLevel * size * 0.24;
  const bassInfluence = m.bassLevel * size * 0.18;
  return baseDistance + combinedWave * size * 0.1 + springInfluence + bassInfluence;
}

function capsuleInitialAngleDeg(i: number): number {
  return i * (360 / NUM_CAPSULES) + i * 7.3;
}

export function computeScale(t: number, m: BubbleAudioModel): number {
  return blended(m, (mode) => scaleFor(mode, t, m));
}

export function computeCapsules(size: number, dpr: number, t: number, m: BubbleAudioModel): CapsuleUniforms {
  const width = size * 0.12;
  const u: CapsuleUniforms = {
    center: new Float32Array(NUM_CAPSULES * 2),
    halfSeg: new Float32Array(NUM_CAPSULES),
    radius: new Float32Array(NUM_CAPSULES),
    rot: new Float32Array(NUM_CAPSULES),
    opacity: new Float32Array(NUM_CAPSULES),
    blur: new Float32Array(NUM_CAPSULES),
    count: NUM_CAPSULES,
  };
  for (let i = 0; i < NUM_CAPSULES; i++) {
    const baseOpacity = 0.2 + i * 0.05;
    const height = capsuleHeight(i, t, size, m);
    const rotation = (capsuleRotationDeg(i, t) * Math.PI) / 180;
    const baseBlur = 2 + i * 0.8;
    const blur = Math.max(0, baseBlur + blended(m, (mode) => blurFor(mode, i, t, m)));
    const radial = capsuleRadialDistance(i, t, size, m);
    const angleRad = (capsuleInitialAngleDeg(i) * Math.PI) / 180;
    u.center[i * 2] = radial * Math.cos(angleRad) * dpr;
    u.center[i * 2 + 1] = radial * Math.sin(angleRad) * dpr;
    u.halfSeg[i] = (Math.max(0, height - width) / 2) * dpr;
    u.radius[i] = (width / 2) * dpr;
    u.rot[i] = rotation;
    u.opacity[i] = blended(m, (mode) => opacityFor(mode, i, t, baseOpacity, m));
    // Swift adds `baseBlur = 2 + index*0.8` points on TOP of the per-mode blur
    // (AnimatedBubbleView.capsuleBlurRadius). Omitting it made the web capsules
    // ~4-6x sharper than native, so the accent stayed a tight cluster in the
    // center instead of a Gaussian dome that spreads across the disk, and left
    // audioResponsive capsules hard-edged whenever springOpacity fell to ~0.
    u.blur[i] = blur * dpr;
  }
  return u;
}
