import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import AnimatedBubble from '../components/AnimatedBubble';
import type { BubbleMode } from '../types';

// Mirror the state-color CSS variables the Swift host injects so the harness passes the exact values used by Header.tsx.
const THEME_VARS: Record<string, string> = {
  '--recording-base': '#8B0000',
  '--recording-accent': '#FF6347',
  '--ready-base': '#348738',
  '--ready-accent': '#C8F0CB',
  '--processing-base': '#7C3AED',
  '--processing-accent': '#DDD6FE',
  '--warning-base': '#FFA500',
};

interface Preset { label: string; mode: BubbleMode; base: string; accent: string; accentDeepen?: number; }

// Match all four Header.tsx combinations, including its RGB-domain accent deepening for both processing variants.
const PRESETS: Preset[] = [
  { label: 'Ready (resting)', mode: 'ambient', base: 'var(--ready-base)', accent: 'var(--ready-accent)' },
  { label: 'Recording', mode: 'audioResponsive', base: 'var(--recording-base)', accent: 'var(--recording-accent)' },
  { label: 'Processing', mode: 'processing', base: 'var(--processing-base)', accent: 'var(--processing-accent)', accentDeepen: 0.55 },
  { label: 'Awaiting input', mode: 'processing', base: 'var(--warning-base)', accent: '#FFFFFF', accentDeepen: 0.55 },
];

function useOscillatingAudio(enabled: boolean): number {
  const [level, setLevel] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    if (!enabled) { setLevel(0); return; }
    const start = performance.now();
    const tick = () => {
      const t = (performance.now() - start) / 1000;
      const v = 0.5 + 0.5 * Math.sin(t * 2.2) * Math.abs(Math.sin(t * 7.0));
      setLevel(Math.max(0, Math.min(1, v)));
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [enabled]);
  return level;
}

function Playground() {
  const [presetIdx, setPresetIdx] = useState(0);
  const [size, setSize] = useState(120);
  const [manualAudio, setManualAudio] = useState(0);
  const [oscillate, setOscillate] = useState(true);
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    for (const [k, v] of Object.entries(THEME_VARS)) root.style.setProperty(k, v);
  }, []);

  const oscillated = useOscillatingAudio(oscillate);
  const preset = PRESETS[presetIdx];
  const audioLevel = preset.mode === 'audioResponsive'
    ? (oscillate ? oscillated : manualAudio)
    : 0;

  const bg = dark ? '#0b0b0c' : '#f2f3f5';
  const panel = dark ? '#17181b' : '#ffffff';
  const text = dark ? '#e6e6e6' : '#1a1a1a';

  return (
    <div style={{ minHeight: '100vh', background: bg, color: text, fontFamily: 'system-ui, sans-serif', padding: 24, boxSizing: 'border-box' }}>
      <h2 style={{ marginTop: 0 }}>Bubble Playground</h2>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 24 }}>
        <label>State:{' '}
          <select value={presetIdx} onChange={(e) => setPresetIdx(Number(e.target.value))}>
            {PRESETS.map((p, i) => <option key={p.label} value={i}>{p.label}</option>)}
          </select>
        </label>
        <label>Size: {size}px{' '}
          <input type="range" min={32} max={320} value={size} onChange={(e) => setSize(Number(e.target.value))} />
        </label>
        <label><input type="checkbox" checked={oscillate} onChange={(e) => setOscillate(e.target.checked)} /> Oscillate audio</label>
        {!oscillate && (
          <label>Audio: {manualAudio.toFixed(2)}{' '}
            <input type="range" min={0} max={1} step={0.01} value={manualAudio} onChange={(e) => setManualAudio(Number(e.target.value))} />
          </label>
        )}
        <label><input type="checkbox" checked={dark} onChange={(e) => setDark(e.target.checked)} /> Dark background</label>
      </div>

      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ background: panel, padding: 24, borderRadius: 16, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <AnimatedBubble size={size} mode={preset.mode} baseColor={preset.base} accentColor={preset.accent} accentDeepen={preset.accentDeepen} audioLevel={audioLevel} />
          <span style={{ fontSize: 12 }}>{preset.label} (interactive)</span>
        </div>
        {PRESETS.map((p) => (
          <div key={p.label} style={{ background: panel, padding: 16, borderRadius: 12, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
            <AnimatedBubble size={44} mode={p.mode} baseColor={p.base} accentColor={p.accent} accentDeepen={p.accentDeepen} audioLevel={p.mode === 'audioResponsive' ? oscillated : 0} />
            <span style={{ fontSize: 11 }}>{p.label} @44</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const el = document.getElementById('root');
if (el) createRoot(el).render(<StrictMode><Playground /></StrictMode>);
