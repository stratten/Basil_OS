"use client";

import { useRef, useEffect, useState } from 'react';

/**
 * CompactFeatureCards - Rich visual feature cards inspired by SuperWhisper's design.
 * Each card has a visual mockup demonstrating the feature in action.
 */

// Mini mockup: Screen awareness visualization
const ScreenAwarenessMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden">
    {/* Mini app windows */}
    <div className="absolute top-3 left-3 w-20 h-14 bg-white/10 rounded border border-white/20 backdrop-blur-sm">
      <div className="flex items-center gap-1 px-1.5 py-1 border-b border-white/10">
        <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
        <div className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
        <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
      </div>
      <div className="p-1.5 space-y-1">
        <div className="h-1 w-12 bg-white/30 rounded" />
        <div className="h-1 w-8 bg-white/20 rounded" />
      </div>
    </div>
    
    <div className="absolute top-6 left-8 w-24 h-16 bg-blue-500/20 rounded border border-blue-400/40 backdrop-blur-sm">
      <div className="flex items-center gap-1 px-1.5 py-1 border-b border-blue-400/30">
        <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
        <div className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
        <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
        <span className="text-[6px] text-blue-300 ml-1">Mail</span>
      </div>
      <div className="p-1.5 space-y-1">
        <div className="h-1 w-16 bg-blue-300/40 rounded" />
        <div className="h-1 w-12 bg-blue-300/30 rounded" />
        <div className="h-1 w-14 bg-blue-300/20 rounded" />
      </div>
    </div>
    
    {/* Scanning effect */}
    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent animate-pulse" 
         style={{ animationDuration: '2s' }} />
    
    {/* Eye indicator */}
    <div className="absolute bottom-2 right-2 flex items-center gap-1.5 bg-cyan-500/20 border border-cyan-400/40 rounded-full px-2 py-0.5">
      <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
      <span className="text-[8px] text-cyan-300 font-medium">Watching</span>
    </div>
  </div>
);

// Mini mockup: Memory/context visualization
const MemoryMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden p-3">
    {/* Memory items */}
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 bg-purple-500/15 border border-purple-400/30 rounded px-2 py-1">
        <div className="w-3 h-3 rounded bg-purple-400 flex items-center justify-center">
          <span className="text-[6px] text-white font-bold">S</span>
        </div>
        <span className="text-[8px] text-purple-200">Prefers concise responses</span>
      </div>
      
      <div className="flex items-center gap-2 bg-purple-500/15 border border-purple-400/30 rounded px-2 py-1">
        <div className="w-3 h-3 rounded bg-pink-400 flex items-center justify-center">
          <span className="text-[6px] text-white font-bold">W</span>
        </div>
        <span className="text-[8px] text-purple-200">Works on Salesforce projects</span>
      </div>
      
      <div className="flex items-center gap-2 bg-purple-500/15 border border-purple-400/30 rounded px-2 py-1">
        <div className="w-3 h-3 rounded bg-violet-400 flex items-center justify-center">
          <span className="text-[6px] text-white font-bold">T</span>
        </div>
        <span className="text-[8px] text-purple-200">Uses British punctuation</span>
      </div>
    </div>
    
    {/* Brain icon */}
    <div className="absolute bottom-2 right-2 w-8 h-8 rounded-full bg-purple-500/20 border border-purple-400/30 flex items-center justify-center">
      <svg className="w-4 h-4 text-purple-300" fill="currentColor" viewBox="0 0 24 24">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
      </svg>
    </div>
  </div>
);

// Mini mockup: Privacy/local-first visualization
const PrivacyMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden">
    {/* Mac with shield */}
    <div className="absolute inset-0 flex items-center justify-center">
      {/* Laptop shape */}
      <div className="relative">
        <div className="w-20 h-14 bg-gray-700 rounded-t-md border-2 border-gray-600 flex items-center justify-center">
          {/* Screen content */}
          <div className="w-16 h-10 bg-gray-900 rounded-sm flex items-center justify-center">
            <svg className="w-6 h-6 text-green-400" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/>
            </svg>
          </div>
        </div>
        <div className="w-24 h-1.5 bg-gray-600 rounded-b-md mx-auto" />
        <div className="w-16 h-0.5 bg-gray-700 rounded mx-auto" />
      </div>
    </div>
    
    {/* Data staying local indicators */}
    <div className="absolute top-2 left-2 flex items-center gap-1 bg-green-500/20 border border-green-400/40 rounded-full px-2 py-0.5">
      <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
      <span className="text-[7px] text-green-300 font-medium">Local first</span>
    </div>
    
    {/* Cloud optional indicator */}
    <div className="absolute top-2 right-2 opacity-50">
      <div className="relative">
        <svg className="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z"/>
        </svg>
        <span className="absolute -bottom-2.5 left-1/2 -translate-x-1/2 text-[5px] text-gray-500 whitespace-nowrap">optional</span>
      </div>
    </div>
    
    <div className="absolute bottom-2 right-2 text-[7px] text-gray-500">
      Nothing retained.
    </div>
  </div>
);

// Mini mockup: Action execution visualization
const ActionMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden p-3">
    {/* Files being organized */}
    <div className="flex items-start gap-3">
      {/* Source: messy */}
      <div className="flex-1">
        <div className="text-[7px] text-gray-500 mb-1 text-center">Before</div>
        <div className="space-y-0.5">
          <div className="h-3 bg-red-500/30 rounded-sm border border-red-400/40 flex items-center px-1">
            <span className="text-[5px] text-red-300 truncate">download.pdf</span>
          </div>
          <div className="h-3 bg-red-500/30 rounded-sm border border-red-400/40 flex items-center px-1">
            <span className="text-[5px] text-red-300 truncate">IMG_2847.jpg</span>
          </div>
          <div className="h-3 bg-red-500/30 rounded-sm border border-red-400/40 flex items-center px-1">
            <span className="text-[5px] text-red-300 truncate">report.csv</span>
          </div>
        </div>
      </div>
      
      {/* Arrow */}
      <div className="flex items-center pt-6">
        <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
        </svg>
      </div>
      
      {/* Target: organized */}
      <div className="flex-1">
        <div className="text-[7px] text-gray-500 mb-1 text-center">After</div>
        <div className="space-y-0.5">
          <div className="h-3 bg-green-500/30 rounded-sm border border-green-400/40 flex items-center px-1">
            <span className="text-[5px] text-green-300 truncate">Documents/</span>
          </div>
          <div className="h-3 bg-green-500/30 rounded-sm border border-green-400/40 flex items-center px-1">
            <span className="text-[5px] text-green-300 truncate">Images/</span>
          </div>
          <div className="h-3 bg-green-500/30 rounded-sm border border-green-400/40 flex items-center px-1">
            <span className="text-[5px] text-green-300 truncate">Data/</span>
          </div>
        </div>
      </div>
    </div>
    
    {/* Action indicator */}
    <div className="absolute bottom-2 left-2 right-2 flex items-center justify-center gap-1 bg-amber-500/20 border border-amber-400/40 rounded px-2 py-1">
      <svg className="w-3 h-3 text-amber-400 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
      <span className="text-[8px] text-amber-300">634 files organized</span>
    </div>
  </div>
);

// Mini mockup: Transcription/dictation visualization
const TranscriptionMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden p-3">
    <div className="flex items-center gap-3 h-full">
      {/* Audio waveform side */}
      <div className="flex-1 flex items-center justify-center gap-0.5">
        {[0.4, 0.7, 1, 0.8, 0.5, 0.9, 0.6, 0.85, 0.45, 0.75].map((height, i) => (
          <div
            key={i}
            className="w-1 bg-rose-400 rounded-full animate-pulse"
            style={{ 
              height: `${height * 40}px`,
              animationDelay: `${i * 0.1}s`,
              animationDuration: '0.8s'
            }}
          />
        ))}
      </div>
      
      {/* Arrow */}
      <svg className="w-4 h-4 text-rose-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
      </svg>
      
      {/* Text output side */}
      <div className="flex-1 space-y-1.5">
        <div className="h-1.5 w-full bg-rose-300/40 rounded" />
        <div className="h-1.5 w-4/5 bg-rose-300/30 rounded" />
        <div className="h-1.5 w-full bg-rose-300/25 rounded" />
        <div className="h-1.5 w-3/5 bg-rose-300/20 rounded" />
      </div>
    </div>
    
    {/* Recording indicator */}
    <div className="absolute bottom-2 right-2 flex items-center gap-1.5 bg-rose-500/20 border border-rose-400/40 rounded-full px-2 py-0.5">
      <div className="w-2 h-2 rounded-full bg-rose-400 animate-pulse" />
      <span className="text-[8px] text-rose-300 font-medium">Recording...</span>
    </div>
  </div>
);

// Mini mockup: Activation methods (wake word + hotkeys)
const ActivationMockup = () => (
  <div className="relative w-full h-32 bg-gradient-to-br from-gray-900 to-gray-800 rounded-lg overflow-hidden p-3">
    <div className="flex flex-col items-center justify-center h-full gap-2">
      {/* Wake word */}
      <div className="flex items-center gap-2">
        <div className="relative">
          <span className="text-[10px] font-medium text-indigo-300">&quot;Hey Basil&quot;</span>
          <div className="absolute -inset-1 bg-indigo-400/20 rounded-full blur-sm animate-pulse" />
        </div>
      </div>
      
      {/* OR divider */}
      <div className="flex items-center gap-2 w-full px-4">
        <div className="flex-1 h-px bg-gray-700" />
        <span className="text-[7px] text-gray-500">or</span>
        <div className="flex-1 h-px bg-gray-700" />
      </div>
      
      {/* Hotkey */}
      <div className="flex items-center gap-1">
        <kbd className="px-1.5 py-0.5 bg-gray-700 border border-gray-600 rounded text-[8px] text-indigo-300 font-mono">⌥</kbd>
        <kbd className="px-1.5 py-0.5 bg-gray-700 border border-gray-600 rounded text-[8px] text-indigo-300 font-mono">⌥</kbd>
      </div>
    </div>
    
    {/* Always ready indicator */}
    <div className="absolute bottom-2 right-2 flex items-center gap-1.5 bg-indigo-500/20 border border-indigo-400/40 rounded-full px-2 py-0.5">
      <div className="w-2 h-2 rounded-full bg-indigo-400" />
      <span className="text-[8px] text-indigo-300 font-medium">Always ready</span>
    </div>
  </div>
);

interface CompactFeatureCardsProps {
  className?: string;
}

const CompactFeatureCards = ({ className = "" }: CompactFeatureCardsProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);
  
  // Click-and-drag scrolling state
  const [isDragging, setIsDragging] = useState(false);
  const [startX, setStartX] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsVisible(true);
          }
        });
      },
      { threshold: 0.2 }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, []);

  // Click-and-drag handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (!scrollContainerRef.current) return;
    setIsDragging(true);
    setStartX(e.pageX - scrollContainerRef.current.offsetLeft);
    setScrollLeft(scrollContainerRef.current.scrollLeft);
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleMouseLeave = () => {
    setIsDragging(false);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !scrollContainerRef.current) return;
    e.preventDefault();
    const x = e.pageX - scrollContainerRef.current.offsetLeft;
    const walk = (x - startX) * 1.5; // Scroll speed multiplier
    scrollContainerRef.current.scrollLeft = scrollLeft - walk;
  };

  const cards = [
    {
      mockup: <TranscriptionMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
        </svg>
      ),
      iconColor: 'text-rose-400',
      title: 'Voice to text, instantly',
      description: 'Dictate anything. Your transcriptions are searchable and include audio playback.',
    },
    {
      mockup: <PrivacyMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
      ),
      iconColor: 'text-green-400',
      title: 'Local first',
      description: 'Everything runs on your Mac. Cloud models are optional, and nothing is retained.',
    },
    {
      mockup: <ActionMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      ),
      iconColor: 'text-amber-400',
      title: 'Actually does things',
      description: 'Not just suggestions. Basil takes real action—organizing files, drafting emails, and more.',
    },
    {
      mockup: <ActivationMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          {/* Center dot */}
          <circle cx="12" cy="12" r="2" strokeWidth={2} />
          {/* Inner arc */}
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.54 8.46a5 5 0 010 7.08" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.46 15.54a5 5 0 010-7.08" />
          {/* Outer arc */}
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.36 5.64a11 11 0 010 12.72" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.64 18.36a11 11 0 010-12.72" />
        </svg>
      ),
      iconColor: 'text-indigo-400',
      title: 'Always ready',
      description: 'Say "Hey Basil" or double-tap Option. No mouse required.',
    },
    {
      mockup: <MemoryMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      ),
      iconColor: 'text-purple-400',
      title: 'Remembers everything (locally)',
      description: 'Your preferences, writing style, and work history. Basil learns and adapts to you.',
    },
    {
      mockup: <ScreenAwarenessMockup />,
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg>
      ),
      iconColor: 'text-cyan-400',
      title: 'Sees your screen',
      description: 'Basil sees what you\'re working on. No need to explain context or copy-paste content.',
    },
  ];

  // Accent colors for each card's glow, border, and background tint
  const accentColors = [
    { glow: 'group-hover:shadow-rose-500/20', bg: 'bg-rose-500/10', tint: 'bg-rose-500/5', borderColor: 'border-rose-800/40 group-hover:border-rose-600/50' },
    { glow: 'group-hover:shadow-green-500/20', bg: 'bg-green-500/10', tint: 'bg-green-500/5', borderColor: 'border-green-800/40 group-hover:border-green-600/50' },
    { glow: 'group-hover:shadow-amber-500/20', bg: 'bg-amber-500/10', tint: 'bg-amber-500/5', borderColor: 'border-amber-800/40 group-hover:border-amber-600/50' },
    { glow: 'group-hover:shadow-indigo-500/20', bg: 'bg-indigo-500/10', tint: 'bg-indigo-500/5', borderColor: 'border-indigo-800/40 group-hover:border-indigo-600/50' },
    { glow: 'group-hover:shadow-purple-500/20', bg: 'bg-purple-500/10', tint: 'bg-purple-500/5', borderColor: 'border-purple-800/40 group-hover:border-purple-600/50' },
    { glow: 'group-hover:shadow-cyan-500/20', bg: 'bg-cyan-500/10', tint: 'bg-cyan-500/5', borderColor: 'border-cyan-800/40 group-hover:border-cyan-600/50' },
  ];

  return (
    <div ref={containerRef} className={`py-16 pb-24 relative z-10 ${className}`}>
      {/* Section Header */}
      <div className="text-center mb-10 px-4">
        <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-gray-900 mb-4">
          Built <span className="bg-gradient-to-r from-purple-600 via-pink-500 to-amber-500 bg-clip-text text-transparent">different</span>.
        </h2>
        <p className="text-lg text-gray-600 max-w-xl mx-auto">
        And by that we mean useful.
        </p>
      </div>

      {/* Cards - Horizontal scrollable slider */}
      <div className="relative max-w-6xl mx-auto z-20 overflow-visible">
        {/* Scroll container - constrained to show ~4.5 cards on desktop */}
        <div 
          ref={scrollContainerRef}
          className={`overflow-x-auto px-4 pt-2 pb-4 ${isDragging ? 'cursor-grabbing select-none' : 'cursor-grab'}`}
          style={{ 
            scrollbarWidth: 'none', 
            msOverflowStyle: 'none',
            WebkitOverflowScrolling: 'touch'
          }}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          onMouseMove={handleMouseMove}
        >
          <div className="flex gap-5 pb-8">
          {cards.map((card, index) => {
            // Get accent color for tint
            const accentTint = [
              'bg-rose-500/5',
              'bg-green-500/5', 
              'bg-amber-500/5',
              'bg-indigo-500/5',
              'bg-purple-500/5',
              'bg-cyan-500/5',
            ][index] ?? 'bg-white/5';
            
            return (
            <div
              key={card.title}
              className={`group relative rounded-2xl transition-all duration-500 hover:-translate-y-1 hover:z-50 w-[300px] flex-shrink-0 ${
                isVisible 
                  ? 'opacity-100 translate-y-0' 
                  : 'opacity-0 translate-y-8'
              }`}
              style={{
                transitionDelay: `${index * 100}ms`,
              }}
            >
              {/* Glass border wrapper */}
              <div 
                className="absolute -inset-[1px] rounded-2xl pointer-events-none"
                style={{
                  background: 'linear-gradient(135deg, rgba(255,255,255,0.4) 0%, rgba(255,255,255,0.1) 40%, rgba(255,255,255,0.05) 60%, rgba(255,255,255,0.2) 100%)',
                }}
              />
              
              {/* Card content container */}
              <div className="relative bg-gray-950/90 backdrop-blur-xl border border-white/[0.15] rounded-2xl overflow-hidden transition-all duration-300 shadow-lg group-hover:shadow-xl">
                {/* Soft color tint overlay */}
                <div className={`absolute inset-0 ${accentTint} pointer-events-none`} />
                
                {/* Glass inner highlight - subtle top edge glow */}
                <div className="absolute inset-0 bg-gradient-to-b from-white/[0.08] via-transparent to-transparent pointer-events-none" />
                
                {/* Visual Mockup */}
                <div className="p-3 pb-0 relative">
                  <div className="relative overflow-hidden rounded-lg">
                    {card.mockup}
                    {/* Subtle shine effect on hover */}
                    <div className="absolute inset-0 bg-gradient-to-tr from-white/0 via-white/5 to-white/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
                  </div>
                </div>
                
                {/* Content */}
                <div className="p-4 pt-3">
                  {/* Title with icon in badge */}
                  <div className="flex items-center gap-2.5 mb-2">
                    <span className={`${card.iconColor} ${accentColors[index]?.bg ?? ''} p-1.5 rounded-lg`}>
                      {card.icon}
                    </span>
                    <h3 className="text-sm font-semibold text-white group-hover:text-white transition-colors">
                      {card.title}
                    </h3>
                  </div>
                  
                  {/* Description */}
                  <p className="text-xs text-gray-400 leading-relaxed group-hover:text-gray-300 transition-colors">
                    {card.description}
                  </p>
                </div>
              </div>
            </div>
          );
          })}
          </div>
        </div>
        {/* Scroll hint - subtle gradient fade on edges */}
        <div className="absolute left-0 top-0 bottom-0 w-8 bg-gradient-to-r from-white to-transparent pointer-events-none hidden sm:block z-10" />
        <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white to-transparent pointer-events-none hidden sm:block z-10" />
        
        {/* Scroll indicator - positioned at bottom, behind cards so shadows paint over */}
        <div className="absolute bottom-0 left-0 right-0 flex justify-center">
          <span className="text-xs text-gray-400 bg-white px-2">← Scroll to see more →</span>
        </div>
      </div>
      
      {/* Hide webkit scrollbar */}
      <style jsx>{`
        div::-webkit-scrollbar {
          display: none;
        }
      `}</style>
    </div>
  );
};

export default CompactFeatureCards;
