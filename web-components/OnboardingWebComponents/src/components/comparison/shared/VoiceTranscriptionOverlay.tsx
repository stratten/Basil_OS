"use client";

import { useState, useEffect } from 'react';

interface VoiceTranscriptionOverlayProps {
  /** The full transcript text to display */
  transcriptText: string;
  /** Whether the overlay is visible */
  isVisible: boolean;
  /** Words to reveal per chunk (simulates natural speech grouping) */
  wordsPerChunk?: number;
  /** Chunks per second (~3 words/chunk at 2.5 chunks/sec = ~150 WPM) */
  chunksPerSecond?: number;
}

/**
 * Animated overlay showing voice transcription with smooth word-chunk reveals.
 * Each chunk fades in smoothly using CSS transitions, similar to SpokenText.
 */
const VoiceTranscriptionOverlay = ({
  transcriptText,
  isVisible,
  wordsPerChunk = 3,
  chunksPerSecond = 2.5,
}: VoiceTranscriptionOverlayProps) => {
  const [revealedChunks, setRevealedChunks] = useState(0);
  const [pulseScale, setPulseScale] = useState(1);

  // Split text into word chunks
  const words = transcriptText.split(' ').filter(w => w.length > 0);
  const chunks: string[] = [];
  for (let i = 0; i < words.length; i += wordsPerChunk) {
    chunks.push(words.slice(i, i + wordsPerChunk).join(' '));
  }
  const totalChunks = chunks.length;

  // Reset and start revealing when visibility changes
  useEffect(() => {
    if (!isVisible) {
      setRevealedChunks(0);
      return;
    }

    // Start revealing chunks
    setRevealedChunks(0);
    const interval = 1000 / chunksPerSecond;
    
    const timer = setInterval(() => {
      setRevealedChunks(prev => {
        const next = prev + 1;
        if (next >= totalChunks) {
          clearInterval(timer);
          return totalChunks;
        }
        return next;
      });
    }, interval);

    return () => clearInterval(timer);
  }, [isVisible, transcriptText, chunksPerSecond, totalChunks]);

  // Pulse animation for mic icon
  useEffect(() => {
    if (!isVisible) return;

    const pulse = () => {
      setPulseScale(1.3);
      setTimeout(() => setPulseScale(1), 400);
    };

    pulse();
    const interval = setInterval(pulse, 800);
    return () => clearInterval(interval);
  }, [isVisible]);

  if (!isVisible) return null;

  return (
    <div 
      className={`absolute bottom-0 left-0 right-0 flex items-center gap-3 px-4 py-3 bg-white/95 backdrop-blur-sm shadow-lg border-t border-blue-200/50 transition-all duration-300 ${
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
      }`}
    >
      {/* Pulsing microphone indicator */}
      <div className="relative flex-shrink-0">
        {/* Pulse ring */}
        <div 
          className="absolute inset-0 bg-blue-500/30 rounded-full transition-transform duration-400"
          style={{ transform: `scale(${pulseScale})` }}
        />
        {/* Inner circle */}
        <div className="relative w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center">
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-white" fill="currentColor">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
          </svg>
        </div>
      </div>

      {/* Transcription text with smooth per-chunk fade-in */}
      <p className="text-sm text-gray-800 leading-snug flex-1">
        {chunks.map((chunk, index) => {
          // Chunk is visible if its index is less than revealedChunks
          const isRevealed = index < revealedChunks;
          
          return (
            <span
              key={index}
              style={{
                opacity: isRevealed ? 1 : 0,
                transition: 'opacity 0.3s ease-out',
              }}
            >
              {chunk}
              {index < chunks.length - 1 ? ' ' : ''}
            </span>
          );
        })}
      </p>
    </div>
  );
};

export default VoiceTranscriptionOverlay;
