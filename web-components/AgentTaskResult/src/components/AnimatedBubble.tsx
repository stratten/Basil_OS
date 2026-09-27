import { useEffect, useRef } from 'react';
import type { BubbleMode } from '../types';
import { BubbleAudioModel } from './bubble/audioModel';
import { BubbleRenderer } from './bubble/bubbleRenderer';
import { computeCapsules } from './bubble/bubbleGeometry';

export type RgbColor = [number, number, number];

export interface RgbTransition {
  from: RgbColor;
  to: RgbColor;
  startedAt: number;
}

export const BUBBLE_COLOR_TRANSITION_MS = 500;

interface Props {
  size: number;
  mode: BubbleMode;
  baseColor: string;
  accentColor: string;
  /**
   * Fraction (0..1) to blend the resolved accent toward the base before
   * screen-blending. Done here in the RGB domain so it is engine-identical;
   * CSS `color-mix()` cannot be used because WebKit does not fold it through the
   * getComputedStyle color probe. 0 leaves the accent untouched.
   */
  accentDeepen?: number;
  audioLevel?: number;
}

function mixRgb(
  a: RgbColor,
  b: RgbColor,
  t: number
): RgbColor {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function easeInOut(progress: number): number {
  return progress * progress * (3 - 2 * progress);
}

export function rgbTransitionValue(transition: RgbTransition, now: number): RgbColor {
  const progress = Math.min(1, Math.max(0, (now - transition.startedAt) / BUBBLE_COLOR_TRANSITION_MS));
  return mixRgb(transition.from, transition.to, easeInOut(progress));
}

export function retargetRgbTransition(transition: RgbTransition, target: RgbColor, now: number): RgbTransition {
  if (transition.to.every((channel, index) => channel === target[index])) return transition;
  return {
    from: rgbTransitionValue(transition, now),
    to: target,
    startedAt: now,
  };
}

function parseRgb(value: string): RgbColor {
  const m = value.match(/(\d+(?:\.\d+)?)/g);
  if (!m || m.length < 3) return [0, 0, 0];
  // WebKit serializes computed colors either as legacy `rgb(r, g, b)` with
  // 0..255 integer channels, or as CSS Color 4 `color(srgb r g b)` with 0..1
  // float channels (notably for `color-mix()` results). Normalize to 0..1 by
  // detecting the notation rather than blindly dividing by 255, otherwise a
  // `color(srgb ...)` string collapses to near-black.
  const isSrgbFloat = /color\(\s*srgb/i.test(value);
  const scale = isSrgbFloat ? 1 : 255;
  return [Number(m[0]) / scale, Number(m[1]) / scale, Number(m[2]) / scale];
}

export default function AnimatedBubble({ size, mode, baseColor, accentColor, accentDeepen = 0, audioLevel = 0 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const modeRef = useRef<BubbleMode>(mode);
  const audioRef = useRef(audioLevel);
  const colorRef = useRef({ base: baseColor, accent: accentColor });
  const deepenRef = useRef(accentDeepen);
  modeRef.current = mode;
  audioRef.current = audioLevel;
  colorRef.current = { base: baseColor, accent: accentColor };
  deepenRef.current = accentDeepen;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = BubbleRenderer.create(canvas);
    if (!renderer) return;
    const model = new BubbleAudioModel();
    // Supersample the backing store above display resolution. The circle edge is
    // computed analytically in the fragment shader (MSAA/antialias:true does not
    // apply to it), so its smoothness is limited by framebuffer resolution. At
    // native dpr the cardinal arcs stair-step ("horizontal delineations"); a 2x
    // supersample renders well above the monitor and lets the browser downsample,
    // giving a smooth edge regardless of devicePixelRatio. The bubble is tiny, so
    // the extra fragments are negligible. `dpr` feeds both the backing size and
    // the capsule geometry scale, so everything stays proportional.
    const SUPERSAMPLE = 2;
    const dpr = ((typeof window !== 'undefined' && window.devicePixelRatio) || 1) * SUPERSAMPLE;
    renderer.resize(size, dpr);

    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;left:-9999px;width:0;height:0;';
    document.body.appendChild(probe);
    const resolve = (value: string): RgbColor => {
      probe.style.color = value;
      return parseRgb(getComputedStyle(probe).color);
    };

    let raf = 0;
    let last = performance.now();
    let lastMode: BubbleMode = modeRef.current;
    let lastAudio = audioRef.current;
    const initialBase = resolve(colorRef.current.base);
    const initialAccent = mixRgb(resolve(colorRef.current.accent), initialBase, deepenRef.current);
    let baseTransition: RgbTransition = { from: initialBase, to: initialBase, startedAt: last };
    let accentTransition: RgbTransition = { from: initialAccent, to: initialAccent, startedAt: last };
    let lastColorAt = last;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const now = performance.now();
      let dt = (now - last) / 1000;
      last = now;
      if (dt > 0.1) dt = 0.1;
      if (modeRef.current !== lastMode) {
        model.setAnimationMode(modeRef.current);
        lastMode = modeRef.current;
      }
      if (audioRef.current !== lastAudio) {
        model.ingestAudioLevel(audioRef.current);
        lastAudio = audioRef.current;
      }
      model.advance(dt);
      if (now - lastColorAt > 200) {
        const targetBase = resolve(colorRef.current.base);
        const targetAccent = mixRgb(resolve(colorRef.current.accent), targetBase, deepenRef.current);
        baseTransition = retargetRgbTransition(baseTransition, targetBase, now);
        accentTransition = retargetRgbTransition(accentTransition, targetAccent, now);
        lastColorAt = now;
      }
      const t = now / 1000;
      const baseSrgb = rgbTransitionValue(baseTransition, now);
      const accentSrgb = rgbTransitionValue(accentTransition, now);
      // No CSS scale on the canvas: the shader hard-clips every capsule to the
      // fixed circle (uRadius = px/2), so scaling the element would grow the
      // whole disc past its `size` box (purple spilling outside the circle).
      // The "breathing"/growth read is carried entirely by the interior capsule
      // animation (height/radial expansion), never by the bubble's outer bound.
      renderer.draw(baseSrgb, accentSrgb, computeCapsules(size, dpr, t, model));
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      probe.remove();
      renderer.dispose();
    };
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ width: size, height: size }}
    />
  );
}
