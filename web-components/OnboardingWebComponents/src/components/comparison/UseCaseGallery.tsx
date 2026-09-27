"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { AssistantSessionPanel } from './assistantSession';
import { AgentTaskPanel } from './agentTask';
import { VoiceTranscriptionOverlay } from './shared';
import {
  emailUseCase,
  textUseCase,
  researchUseCase,
  meetingUseCase,
  writingUseCase,
  codeUseCase,
  slackUseCase,
  UseCase,
} from './assistantSession/contexts';
import {
  desktopCleanupUseCase,
  documentGenerationUseCase,
  productSearchUseCase,
} from './agentTask/contexts';

// ============================================================================
// USE CASE REGISTRY
// ============================================================================

// AssistantSession use cases
const ASSISTANT_SESSION_CASES: UseCase[] = [
  emailUseCase,
  textUseCase,
  slackUseCase,
  researchUseCase,
  meetingUseCase,
  writingUseCase,
  codeUseCase,
];

// Combined for selector display
interface SelectorItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  type: 'assistantSession' | 'agentTask';
}

// AgentTask use cases
const MINION_CASES = [
  desktopCleanupUseCase,
  documentGenerationUseCase,
  productSearchUseCase,
];

const ALL_CASES: SelectorItem[] = [
  ...ASSISTANT_SESSION_CASES.map(uc => ({ ...uc, type: 'assistantSession' as const })),
  ...MINION_CASES.map(uc => ({
    id: uc.id,
    label: uc.label,
    icon: uc.icon,
    type: 'agentTask' as const,
  })),
];

// ============================================================================
// GALLERY COMPONENT
// ============================================================================

interface UseCaseGalleryProps {
  className?: string;
}

const UseCaseGallery = ({ className = "" }: UseCaseGalleryProps) => {
  const [selectedId, setSelectedId] = useState<string>(ALL_CASES[0]?.id || '');
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [hasStartedDrawing, setHasStartedDrawing] = useState(false);
  const animationRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Find selected case info
  const selectedItem = ALL_CASES.find(c => c.id === selectedId) || ALL_CASES[0];
  const isAgentTask = selectedItem?.type === 'agentTask';
  
  // Get AssistantSession case if applicable
  const selectedVSCase = !isAgentTask 
    ? ASSISTANT_SESSION_CASES.find(uc => uc.id === selectedId) 
    : undefined;
  
  // Get AgentTask case if applicable
  const selectedAgentTaskCase = isAgentTask
    ? MINION_CASES.find(uc => uc.id === selectedId)
    : undefined;

  const playAnimation = useCallback(() => {
    setCurrentTime(0);
    lastTimeRef.current = 0;
    setHasStartedDrawing(false);
    setTimeout(() => setHasStartedDrawing(true), 50);
    setIsPlaying(true);
  }, []);

  const handleSelectCase = (id: string) => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }
    setSelectedId(id);
    playAnimation();
  };

  // Calculate duration based on selected case type
  const minDuration = useMemo(() => {
    if (isAgentTask && selectedAgentTaskCase) {
      return selectedAgentTaskCase.duration;
    }
    if (!selectedVSCase) return 16;
    const streamStartTime = 11;
    const charsPerSecond = 80;
    const streamingTime = selectedVSCase.outputText.length / charsPerSecond;
    return streamStartTime + streamingTime + 1;
  }, [isAgentTask, selectedVSCase, selectedAgentTaskCase]);

  // Animation loop
  useEffect(() => {
    if (!isPlaying) return;

    const animate = (timestamp: number) => {
      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
      }
      
      const delta = (timestamp - lastTimeRef.current) / 1000;
      lastTimeRef.current = timestamp;
      
      setCurrentTime(prev => {
        const next = prev + delta;
        if (next >= minDuration) {
          setIsPlaying(false);
          return minDuration;
        }
        return next;
      });
      
      if (isPlaying) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };
    
    animationRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isPlaying, minDuration]);

  // Intersection observer for auto-play
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isPlaying && currentTime === 0) {
          playAnimation();
        }
      },
      { threshold: 0.3 }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, [playAnimation, isPlaying, currentTime]);

  return (
    <section ref={containerRef} className={`pt-16 pb-10 sm:pt-24 sm:pb-14 min-h-screen flex flex-col ${className}`}>
      <div className="max-w-6xl mx-auto px-4 flex-1 flex flex-col w-full">
        {/* Header */}
        <div className="text-center mb-6">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-3">
            Works wherever you are.
          </h2>
          <p className="text-white max-w-2xl mx-auto">
            Email, Slack, that Google Doc you've been avoiding—we don't judge. Actually we do, but we won't say anything. We're classy like that. <br/> <br/> Just press the hotkey or say "Hey Basil" and tell it what to do.
          </p>
        </div>

        {/* Use Case Selector - Two Groups */}
        <div className="space-y-4 mb-4">
          {/* AssistantSession - "Say the thing" */}
          <div>
            <p className="text-center text-sm font-medium text-emerald-400 mb-2">Say the thing</p>
            <div className="flex flex-wrap justify-center gap-2 sm:gap-3">
              {ASSISTANT_SESSION_CASES.map((item) => (
            <button
                  key={item.id}
                  onClick={() => handleSelectCase(item.id)}
              className={`
                flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium
                transition-all duration-300 ease-out
                    ${selectedId === item.id
                  ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-500/25 scale-105'
                      : 'bg-white/10 text-white/80 hover:bg-white/20 hover:text-white'
                }
              `}
            >
                  <span className="w-5 h-5">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* AgentTasks - "Do the thing" */}
          <div>
            <p className="text-center text-sm font-medium text-blue-400 mb-2">Do the thing</p>
            <div className="flex flex-wrap justify-center gap-2 sm:gap-3">
              {MINION_CASES.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleSelectCase(item.id)}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium
                    transition-all duration-300 ease-out
                    ${selectedId === item.id
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/25 scale-105'
                      : 'bg-white/10 text-white/80 hover:bg-white/20 hover:text-white'
                    }
                  `}
                >
                  <span className="w-5 h-5">{item.icon}</span>
                  <span>{item.label}</span>
            </button>
          ))}
            </div>
          </div>
        </div>

        {/* Demo Panel - fills all remaining vertical space between the use-case
            selectors above and the hotkey hint below, so the simulated viewport
            opens at its full height instead of the natural-content minimum and
            then visibly resizing as content streams in. min-h floors keep the
            panel usable on short viewports where flex-1 would collapse it. */}
        <div 
          className="relative rounded-2xl border-2 border-gray-700 shadow-lg flex-1 min-h-[640px] sm:min-h-[620px] bg-cover bg-center overflow-hidden"
          style={{ backgroundImage: "url('/images/home/Desktop_Background.jpg')" }}
        >
          {isAgentTask && selectedAgentTaskCase ? (
            <AgentTaskPanel 
              useCase={selectedAgentTaskCase}
              currentTime={currentTime} 
              isDrawing={hasStartedDrawing}
            />
          ) : selectedVSCase ? (
            <AssistantSessionPanel
              useCase={selectedVSCase}
              currentTime={currentTime}
                isDrawing={hasStartedDrawing} 
            />
          ) : null}
          
          {/* Voice Transcription Overlay - positioned at very bottom of demo container */}
          {/* Only show for voice-based interactions, not for text entry mode */}
          {(() => {
            // For AssistantSessions: calculate dynamic reveal rate to fit in 4-second recording window (3s to 7s)
            const vsText = selectedVSCase?.requestText || '';
            const vsWordCount = vsText.split(' ').filter((w: string) => w.length > 0).length;
            const vsChunks = Math.ceil(vsWordCount / 3); // 3 words per chunk
            const vsRevealTime = 3.5; // seconds available (3s to 6.5s, with 0.5s buffer before processing at 7s)
            const vsChunksPerSecond = Math.max(2.5, vsChunks / vsRevealTime);
            
            // For agentTasks: use full command text with standard reveal rate
            // Capture phases are sized to accommodate the text at 2.5 chunks/sec
            const agentTaskText = selectedAgentTaskCase?.commandText || '';
            
            return (
              <VoiceTranscriptionOverlay
                transcriptText={isAgentTask ? agentTaskText : vsText}
                isVisible={
                  hasStartedDrawing && (
                    isAgentTask 
                      ? (
                          selectedAgentTaskCase?.getPhase(currentTime) === 'capture' && 
                          !selectedAgentTaskCase?.getIsTextEntryActive?.(currentTime)
                        )
                      : (currentTime >= 3 && currentTime < 7)
                  )
                }
                chunksPerSecond={isAgentTask ? 2.5 : vsChunksPerSecond}
              />
            );
          })()}
        </div>

        {/* Hotkey hint - changes based on selected feature type */}
        <div className="text-center mt-4 text-xs text-white flex items-center justify-center gap-2">
          {isAgentTask ? (
            selectedAgentTaskCase?.isTextEntryMode ? (
              <>
                <kbd className="px-1.5 py-0.5 bg-white/20 rounded border border-white/30 font-mono text-[10px] text-white">⌥</kbd>
                <kbd className="px-1.5 py-0.5 bg-white/20 rounded border border-white/30 font-mono text-[10px] text-white">Space</kbd>
                <span>Press Option+Space then click keyboard icon to type.</span>
              </>
            ) : (
              <>
                <kbd className="px-1.5 py-0.5 bg-white/20 rounded border border-white/30 font-mono text-[10px] text-white">⌥</kbd>
                <kbd className="px-1.5 py-0.5 bg-white/20 rounded border border-white/30 font-mono text-[10px] text-white">Space</kbd>
                <span>Press Option+Space to invoke, or say "Hey Basil".</span>
              </>
            )
          ) : (
            <>
          <kbd className="px-1.5 py-0.5 bg-white/20 rounded border border-white/30 font-mono text-[10px] text-white">⌥⌥</kbd>
          <span>Double-tap Option to invoke</span>
            </>
          )}
        </div>

        {/* Replay hint */}
        <div className="text-center mt-6">
          <p className="text-sm text-white">
            {isPlaying ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                Playing...
              </span>
            ) : currentTime > 0 ? (
              <button 
                onClick={playAnimation}
                className="text-emerald-400 hover:text-emerald-300 transition-colors flex items-center justify-center gap-1.5 mx-auto"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z"/>
                </svg>
                Replay
              </button>
            ) : (
              <span>Select a scenario above</span>
            )}
          </p>
        </div>

        {/* Transcription note */}
        <p className="text-center text-xs text-white/60 mt-6 max-w-sm mx-auto">
          Basil also does standard transcription. But unlike some apps, we don't, like, make that our whole personality. 
        </p>
      </div>
    </section>
  );
};

export default UseCaseGallery;
