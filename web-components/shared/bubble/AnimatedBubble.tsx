import { useEffect, useRef } from 'react';
import { BubbleAudioModel } from './audioModel';
import { BubbleRenderer } from './bubbleRenderer';
import { computeCapsules } from './bubbleGeometry';

export type BubbleMode = 'ambient' | 'audioResponsive' | 'processing';

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
  /** Fraction from zero to one used to blend the resolved accent toward the base in RGB before screen blending; zero leaves the accent unchanged. */
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
  // WebKit serializes computed colors as either 0-255 legacy rgb or 0-1 CSS Color 4 srgb, so detect the notation before normalization.
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
    // Supersample the small backing store because the analytically clipped circle edge does not benefit from WebGL antialiasing; dpr scales both the backing size and capsule geometry.
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
      // Do not CSS-scale the canvas because the shader clips to a fixed circle; the interior capsule animation alone provides the breathing effect.
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
