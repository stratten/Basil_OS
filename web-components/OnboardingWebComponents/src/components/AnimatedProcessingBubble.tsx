"use client";

import { useEffect, useRef, useState } from 'react';
import {
  DEFAULT_PROCESSING_BASE_HEX,
  DEFAULT_PROCESSING_ACCENT_HEX,
} from '../theme/generated-defaults';

interface AnimatedProcessingBubbleProps {
  size?: number;
  baseColor?: string;
  accentColor?: string;
  isProcessing?: boolean; // true = active processing animation, false = calm idle state
}

/**
 * Canonical bubble colour palette for the onboarding mocks.
 *
 * Semantics (must stay in sync with `AestheticSystem.Colors.bubbleColors`):
 *   - `idle`       -> ready green     (Basil is ready to receive input)
 *   - `recording`  -> red             (Basil is actively listening)
 *   - `processing` -> Royal Purple    (Basil is working on the request)
 *
 * The key name `idle` is retained for source compatibility across the
 * mocks, but it represents the ambient/ready bubble state, not a disabled
 * or off state. If the Swift enum is later renamed to `.ready`, this key
 * and its consumers can be renamed in the same pass.
 *
 * The `processing` entry is the only colour pair that is build-time
 * generated: its hex strings come from `theme/generated-defaults.ts`,
 * which `scripts/generate_processing_color_defaults.py` regenerates from
 * the Swift literals on `AestheticSystem.Colors.defaultProcessing*` as
 * STEP 0 of the canonical asset builders. Editing those Swift literals
 * (and re-running a build) is the only way to change the processing
 * colour anywhere in the app -- the onboarding mocks pick it up via this
 * constant.
 *
 * `idle` and `recording` mirror the fixed state colour pairs defined in
 * `AestheticSystem.Colors.readyBase/readyAccent` and `recordingBase/
 * recordingAccent`. They are not generated because they aren't user-
 * configurable on the Swift side either; if either becomes user-
 * configurable later, lift it through the same generator pipeline so
 * Swift stays the single source of truth.
 */
export const BUBBLE_COLORS = {
  idle: { base: '#348738', accent: '#C8F0CB' },
  recording: { base: '#8B0000', accent: '#FF6347' },
  processing: {
    base: DEFAULT_PROCESSING_BASE_HEX,
    accent: DEFAULT_PROCESSING_ACCENT_HEX,
  },
} as const;

// Helper to interpolate between two hex colors
const interpolateColor = (color1: string, color2: string, factor: number): string => {
  const hex1 = color1.replace('#', '');
  const hex2 = color2.replace('#', '');
  
  const r1 = parseInt(hex1.substring(0, 2), 16);
  const g1 = parseInt(hex1.substring(2, 4), 16);
  const b1 = parseInt(hex1.substring(4, 6), 16);
  
  const r2 = parseInt(hex2.substring(0, 2), 16);
  const g2 = parseInt(hex2.substring(2, 4), 16);
  const b2 = parseInt(hex2.substring(4, 6), 16);
  
  const r = Math.round(r1 + (r2 - r1) * factor);
  const g = Math.round(g1 + (g2 - g1) * factor);
  const b = Math.round(b1 + (b2 - b1) * factor);
  
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
};

/**
 * AnimatedProcessingBubble - Faithful recreation of the SwiftUI AnimatedBubbleView.
 * Supports "processing" mode (active animation) and "idle" mode (calm, subtle breathing).
 * Uses requestAnimationFrame for smooth, continuous animation matching the app's 33fps timer approach.
 * Capsule properties (opacity, height, blur, rotation, offset) are calculated per-frame using sin/cos.
 * On mobile, uses reduced blur for better GPU performance.
 * Color transitions are smoothly interpolated over ~600ms when state changes.
 */
const AnimatedProcessingBubble = ({
  size = 44,
  baseColor = BUBBLE_COLORS.processing.base,
  accentColor = BUBBLE_COLORS.processing.accent,
  isProcessing = true
}: AnimatedProcessingBubbleProps) => {
  const numberOfCapsules = 8;
  const [currentTime, setCurrentTime] = useState(0);
  const animationRef = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  
  // Smooth color transition state
  const [colorTransition, setColorTransition] = useState(isProcessing ? 1 : 0);
  const targetColorRef = useRef(isProcessing ? 1 : 0);
  const colorTransitionSpeed = 0.03; // ~600ms transition at 30fps

  // Update target when isProcessing changes
  useEffect(() => {
    targetColorRef.current = isProcessing ? 1 : 0;
  }, [isProcessing]);

  // Animation loop using requestAnimationFrame - throttled to ~30fps for performance
  useEffect(() => {
    const targetFPS = 30;
    const frameInterval = 1000 / targetFPS;
    let lastFrameTime = 0;

    const animate = (timestamp: number) => {
      if (startTimeRef.current === null) {
        startTimeRef.current = timestamp;
        lastFrameTime = timestamp;
      }
      
      // Throttle to target FPS
      const timeSinceLastFrame = timestamp - lastFrameTime;
      
      if (timeSinceLastFrame >= frameInterval) {
        // Convert to seconds (matching Swift's Date().timeIntervalSinceReferenceDate approach)
        const elapsed = (timestamp - startTimeRef.current) / 1000;
        setCurrentTime(elapsed);
        
        // Smoothly interpolate color transition towards target
        setColorTransition(prev => {
          const target = targetColorRef.current;
          if (Math.abs(prev - target) < 0.01) return target;
          
          // Ease towards target
          const diff = target - prev;
          return prev + diff * colorTransitionSpeed * (timeSinceLastFrame / frameInterval);
        });
        
        lastFrameTime = timestamp;
      }
      
      animationRef.current = requestAnimationFrame(animate);
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current !== null) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [colorTransitionSpeed]);

  // Calculate capsule opacity
  const getCapsuleOpacity = (capsuleIndex: number): number => {
    if (!isProcessing) {
      // Idle mode: gentle, uniform opacity
      const baseOpacity = 0.4 + capsuleIndex * 0.03;
      const breathPhase = (currentTime * 0.3) + capsuleIndex * 0.2;
      const breathCycle = (Math.sin(breathPhase) + 1) / 2;
      return baseOpacity + breathCycle * 0.15;
    }
    
    // Processing mode: sharp cyclical peaks
    const baseOpacity = 0.2 + capsuleIndex * 0.05;
    const cyclePhase = (currentTime * 1.5) + capsuleIndex * 0.8;
    const rawCycle = (Math.sin(cyclePhase) + 1) / 2;
    const sharpCycle = Math.pow(rawCycle, 0.5) * 0.9;
    return Math.min(1.0, baseOpacity + sharpCycle);
  };

  // Calculate capsule height
  const getCapsuleHeight = (capsuleIndex: number): number => {
    const baseHeight = size * 0.18;
    
    if (!isProcessing) {
      // Idle mode: minimal height variation, gentle breathing
      const breathPhase = (currentTime * 0.3) + capsuleIndex * 0.15;
      const breathStretch = (Math.sin(breathPhase) + 1) / 2;
      return baseHeight + breathStretch * size * 0.03;
    }
    
    // Processing mode: wave stretches
    const wavePhase1 = (currentTime * 2.0) + capsuleIndex * 0.7;
    const waveStretch1 = (Math.sin(wavePhase1) + 1) / 2;
    
    const wavePhase2 = (currentTime * 0.8) + capsuleIndex * 0.3;
    const waveStretch2 = (Math.cos(wavePhase2) + 1) / 2;
    
    const combinedWaveStretch = (waveStretch1 * 0.7 + waveStretch2 * 0.3);
    
    const processingPhase = (currentTime * 1.2) + capsuleIndex * 0.6;
    const modeStretch = ((Math.sin(processingPhase) + 1) / 2) * size * 0.25;
    
    return baseHeight + (combinedWaveStretch * size * 0.08) + modeStretch;
  };

  // Calculate capsule blur radius (reduced for performance - blur is GPU intensive)
  const getCapsuleBlur = (capsuleIndex: number): number => {
    // Reduced blur values by ~50% for better performance
    const baseBlur = 1 + capsuleIndex * 0.4;
    
    if (!isProcessing) {
      // Idle mode: consistent, soft blur
      return baseBlur + 0.5;
    }
    
    // Processing mode: sin wave pattern with reduced amplitude
    const processingPhase = (currentTime * 1.0) + capsuleIndex * 0.5;
    const blurInfluence = ((Math.sin(processingPhase) + 1) / 2) * 1.5;
    return baseBlur + blurInfluence;
  };

  // Calculate capsule rotation angle
  const getCapsuleRotation = (capsuleIndex: number): number => {
    if (!isProcessing) {
      // Idle mode: very slow, gentle rotation
      const slowRotation = currentTime * 1.0;
      return slowRotation + capsuleIndex * 45;
    }
    
    // Processing mode: active rotation
    const subtleContinuousRotation = currentTime * 5.0;
    
    const wavePhase = (currentTime * 2.0) + capsuleIndex * 0.7;
    const waveRotation = Math.sin(wavePhase) * 30.0;
    
    const secondaryPhase = (currentTime * 1.2) + capsuleIndex * 0.5;
    const secondaryRotation = Math.cos(secondaryPhase) * 15.0;
    
    return subtleContinuousRotation + waveRotation + secondaryRotation + capsuleIndex * 10;
  };

  // Calculate capsule radial distance
  const getCapsuleRadialDistance = (capsuleIndex: number): number => {
    const baseDistance = size * 0.05;
    
    if (!isProcessing) {
      // Idle mode: minimal movement, gentle pulse
      const breathPhase = (currentTime * 0.3) + capsuleIndex * 0.1;
      const breathPulse = (Math.sin(breathPhase) + 1) / 2;
      return baseDistance + breathPulse * size * 0.02;
    }
    
    // Processing mode: active wave motion
    const wavePhase1 = (currentTime * 2.0) + capsuleIndex * 0.7;
    const waveAmplitude1 = (Math.sin(wavePhase1) + 1) / 2;
    
    const wavePhase2 = (currentTime * 0.9) + capsuleIndex * 0.4;
    const waveAmplitude2 = (Math.cos(wavePhase2) + 1) / 2;
    
    const combinedAmplitude = (waveAmplitude1 * 0.6 + waveAmplitude2 * 0.4);
    
    return baseDistance + (combinedAmplitude * size * 0.1);
  };

  // Calculate capsule initial angle
  const getCapsuleAngle = (capsuleIndex: number): number => {
    const baseAngle = capsuleIndex * (360 / numberOfCapsules);
    const uniqueOffset = capsuleIndex * 7.3;
    return baseAngle + uniqueOffset;
  };

  // Calculate bubble scale effect
  const getBubbleScale = (): number => {
    if (!isProcessing) {
      // Idle mode: very subtle breathing
      return 1.0 + Math.sin(currentTime * 0.4) * 0.015;
    }
    // Processing mode: subtle "thinking" pulse
    return 1.0 + Math.sin(currentTime * 0.8) * 0.04;
  };

  // Calculate capsule position
  const getCapsulePosition = (capsuleIndex: number) => {
    const angle = getCapsuleAngle(capsuleIndex);
    const radialDistance = getCapsuleRadialDistance(capsuleIndex);
    const angleRad = (angle * Math.PI) / 180;
    
    return {
      x: radialDistance * Math.cos(angleRad),
      y: radialDistance * Math.sin(angleRad)
    };
  };

  // Ready/ambient state colors (the non-processing resting palette).
  // Sourced from the canonical BUBBLE_COLORS palette so every bubble
  // surface (this component + every mock that consumes it) shares one set
  // of constants instead of duplicating hex literals. The variable names
  // stay `idle*` to match the `isProcessing` prop contract, but the pair
  // is the ready-green palette from BUBBLE_COLORS.idle.
  const idleBaseColor = BUBBLE_COLORS.idle.base;
  const idleAccentColor = BUBBLE_COLORS.idle.accent;

  // Use smoothly interpolated colors based on colorTransition (0 = idle, 1 = processing)
  const effectiveBaseColor = interpolateColor(idleBaseColor, baseColor, colorTransition);
  const effectiveAccentColor = interpolateColor(idleAccentColor, accentColor, colorTransition);

  // Processing uses derived shades instead of extra persisted defaults, keeping
  // Royal Purple as the only configured source while letting the animation feel richer.
  const processingHighlightColor = interpolateColor(effectiveAccentColor, effectiveBaseColor, 0.18);
  const processingMidColor = interpolateColor(effectiveAccentColor, effectiveBaseColor, 0.42);
  const effectiveBubbleBackground = isProcessing
    ? `radial-gradient(circle at 35% 28%, ${processingHighlightColor} 0%, ${processingMidColor} 42%, ${effectiveBaseColor} 100%)`
    : effectiveBaseColor;

  const getCapsuleColor = (capsuleIndex: number): string => {
    if (!isProcessing) {
      return effectiveAccentColor;
    }

    const colorPhase = (currentTime * 0.55) + capsuleIndex * 0.9;
    const animatedBlend = 0.12 + ((Math.sin(colorPhase) + 1) / 2) * 0.48;
    return interpolateColor(effectiveAccentColor, effectiveBaseColor, animatedBlend);
  };

  // Capsule width multiplier
  const capsuleWidthMultiplier = 0.12;

  return (
    <div
      className="relative rounded-full overflow-hidden transition-colors duration-500"
      style={{
        width: size,
        height: size,
        background: effectiveBubbleBackground,
        transform: `scale(${getBubbleScale()})`,
        willChange: 'transform',
      }}
    >
      {/* Capsule elements */}
      {Array.from({ length: numberOfCapsules }, (_, i) => {
        const position = getCapsulePosition(i);
        const rotation = getCapsuleRotation(i);
        const height = getCapsuleHeight(i);
        const opacity = getCapsuleOpacity(i);
        const blur = getCapsuleBlur(i);

        return (
          <div
            key={i}
            className="absolute rounded-full"
            style={{
              width: size * capsuleWidthMultiplier,
              height: height,
              backgroundColor: getCapsuleColor(i),
              opacity: opacity,
              // Apply reduced blur on mobile (already calculated smaller in getCapsuleBlur)
              filter: `blur(${blur}px)`,
              mixBlendMode: 'screen',
              left: '50%',
              top: '50%',
              transform: `translate(-50%, -50%) translate(${position.x}px, ${position.y}px) rotate(${rotation}deg)`,
              willChange: 'transform, opacity',
            }}
          />
        );
      })}
    </div>
  );
};

export default AnimatedProcessingBubble;
