"use client";

import React from 'react';
import ReactDOM from 'react-dom/client';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import '../styles.css';

import { AssistantSessionPanel } from '../components/comparison/assistantSession';
import { AgentTaskPanel } from '../components/comparison/agentTask';
import { VoiceTranscriptionOverlay } from '../components/comparison/shared';
import {
  emailUseCase,
  textUseCase,
  researchUseCase,
  meetingUseCase,
  writingUseCase,
  codeUseCase,
  slackUseCase,
  UseCase,
} from '../components/comparison/assistantSession/contexts';
import {
  desktopCleanupUseCase,
  documentGenerationUseCase,
  productSearchUseCase,
  AgentTaskUseCase,
} from '../components/comparison/agentTask/contexts';
import AssistantSessionWidgetMock from '../components/comparison/assistantSession/AssistantSessionWidgetMock';
import EmailContext from '../components/comparison/assistantSession/contexts/EmailContext';

// ============================================================================
// USE CASE REGISTRIES
// ============================================================================

const ASSISTANT_SESSION_CASES: UseCase[] = [
  emailUseCase,
  textUseCase,
  slackUseCase,
  researchUseCase,
  meetingUseCase,
  writingUseCase,
  codeUseCase,
];

const MINION_CASES: AgentTaskUseCase[] = [
  desktopCleanupUseCase,
  documentGenerationUseCase,
  productSearchUseCase,
];

// ============================================================================
// CONFIG INTERFACE
// ============================================================================

interface OnboardingDemoConfig {
  mode: 'assistantSession' | 'agentTask' | 'assistantSession-text';
  defaultUseCase?: string;
  showUseCases?: string[]; // Filter to specific use cases
  // V2 Onboarding: Timing synchronization with Swift overlay
  transcriptionDuration?: number; // Seconds to wait for transcription overlay
  autoStart?: boolean; // If false, wait for startDemo message
  showCancel?: boolean; // Show cancel flow demo
  showRefine?: boolean; // Show refine flow demo
}

function getConfig(): OnboardingDemoConfig {
  if (typeof window !== 'undefined' && (window as any).basilDemoConfig) {
    return (window as any).basilDemoConfig;
  }
  // Default: show AssistantSessions with email as default
  return {
    mode: 'assistantSession',
    defaultUseCase: 'email',
    autoStart: true,
  };
}

// ============================================================================
// SWIFT BRIDGE - Communication with native overlay
// ============================================================================

interface SwiftBridge {
  onDemoStart?: () => void;
  onDemoPhaseChange?: (phase: string) => void;
  onDemoComplete?: () => void;
}

const swiftBridge: SwiftBridge = {};

// Expose functions that Swift can call via evaluateJavaScript
if (typeof window !== 'undefined') {
  (window as any).basilDemoControl = {
    // Called by Swift when transcription overlay completes
    startDemo: () => {
      swiftBridge.onDemoStart?.();
    },
    // Called by Swift to get current demo state
    getState: () => ({
      isPlaying: false, // Will be updated by component
      currentPhase: 'idle',
    }),
  };
}

// ============================================================================
// CANCEL FLOW DEMO COMPONENT
// ============================================================================

interface CancelFlowDemoProps {
  currentTime: number;
  isDrawing: boolean;
}

/**
 * Demonstrates the cancel flow: user starts recording, changes mind, presses Escape.
 * Uses the actual AssistantSessionWidgetMock and EmailContext components to match app aesthetics.
 * 
 * Timeline (updated):
 * 0-0.5s: Context fades in
 * 0.5s: Widget appears, recording starts
 * 0.5-5.3s: Transcription builds up to "...spreadsheet." (4.8s of speaking, slowed by 20%)
 * 5.3-7.25s: Deliberate pause - considering (1.95s, increased by 30%)
 * 7.25s: "*Presses Esc*" appears in transcription
 * 7.25s: Widget starts dismissing
 * 7.5s+: Widget is gone
 */
const CancelFlowDemo: React.FC<CancelFlowDemoProps> = ({ currentTime, isDrawing }) => {
  const showWidget = currentTime >= 0.5 && currentTime < 7.5;
  const widgetDismissing = currentTime >= 7.25 && currentTime < 7.5;
  
  // Recording state: idle -> recording -> cancelled
  const widgetState: 'idle' | 'recording' | 'processing' | 'complete' = 
    currentTime < 0.5 ? 'idle' :
    currentTime < 7.25 ? 'recording' :
    'idle'; // After cancel, widget is dismissed
  
  // Recording seconds for the widget display (caps at the speaking duration)
  const recordingSeconds = widgetState === 'recording' 
    ? Math.min(7, Math.floor(currentTime - 0.5)) 
    : 0;
  
  // Request text builds up during recording - includes the self-interruption
  const fullRequestText = "Actually, cross-reference column G with the normalised satisfaction scores and— No. They've seen the spreadsheet. They're not ready for the pivot table.";
  
  // Text reveal: builds up over 0.5-5.3s (4.8 seconds, slowed by 20%), then holds during the pause
  const speakingProgress = Math.min(1, (currentTime - 0.5) / 4.8);
  const displayedRequestText = widgetState === 'recording' && currentTime > 0.5
    ? fullRequestText.slice(0, Math.floor(speakingProgress * fullRequestText.length))
    : "";

  return (
    <div className="relative w-full h-full grid grid-cols-2 gap-4 p-4">
      {/* Left: Email context - Kevin's reply to our user's "polite" response */}
      <div 
        className={`transition-opacity duration-500 ${
          isDrawing ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <EmailContext />
      </div>

      {/* Right: AssistantSession Widget - aligned to top like other demos */}
      <div className="flex items-start justify-center pt-4">
        {showWidget && (
          <div 
            className={`transition-all duration-300 ${
              widgetDismissing ? 'opacity-0 scale-95' : 'opacity-100 scale-100'
            }`}
          >
            <AssistantSessionWidgetMock
              state={widgetState}
              requestText={displayedRequestText}
              recordingSeconds={recordingSeconds}
            />
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================================================
// REFINE FLOW DEMO COMPONENT
// ============================================================================

interface RefineFlowDemoProps {
  currentTime: number;
  isDrawing: boolean;
}

/**
 * Demonstrates the refine flow: user gets a response, clicks Refine to improve it.
 * Uses the actual AssistantSessionWidgetMock and EmailContext components.
 * Airport rankings themed - refining a response to brother-in-law's dismissal.
 * 
 * Timeline:
 * 0-0.5s: Context fades in
 * 0.5-1s: Widget appears with initial completed response
 * 1-4s: User reads the initial response
 * 4-4.5s: Refine button highlighted, user clicks
 * 4.5-8s: Widget recording refinement
 * 8-11s: Processing refinement
 * 11s+: Refined response complete
 */
const RefineFlowDemo: React.FC<RefineFlowDemoProps> = ({ currentTime, isDrawing }) => {
  // Initial request and response (defending airport rankings methodology)
  const initialRequest = "Help me respond to Kevin's claim that the Feng Shui Palpability Index isn't a real thing";
  const initialResponse = `I appreciate you taking the time to read my methodology, and I understand it might seem elaborate at first glance.

The Feng Shui Palpability Index is admittedly a somewhat tongue-in-cheek name for what is actually a composite measure of terminal flow, ambient lighting quality, and spatial coherence—`;

  // Refinement and improved response  
  const refinementRequest = "Make it more confident. Really emphasize the rigour of the methodology.";
  const refinedResponse = `Kevin,

The Feng Shui Palpability Index is absolutely a real thing—I created it. That's how indices work.

This isn't arbitrary preference—it's METHODOLOGY. The FSPI aggregates 14 distinct measurable factors across terminal design, validated against passenger satisfaction surveys from 47 airports over 8 years.

The index captures:
• Terminal flow efficiency (measured via walking path analysis)
• Ambient stress indicators (lighting, acoustics, signage clarity)
• Spatial coherence (wayfinding intuitiveness, gate proximity logic)
• Outlet density per gate area (obviously critical)

The methodology has been refined through 47 iterations. Version 12 was indeed flawed—that's documented in the postmortem. But v47 is robust.

I've attached a one-pager. It has diagrams.`;

  // Widget states based on timeline
  const showWidget = currentTime >= 0.5;
  const showRefineHighlight = currentTime >= 3.5 && currentTime < 4.5;
  const isRefining = currentTime >= 4.5;
  
  const widgetState: 'idle' | 'recording' | 'processing' | 'complete' = 
    currentTime < 0.5 ? 'idle' :
    currentTime < 4.5 ? 'complete' :    // Initial response complete
    currentTime < 8 ? 'recording' :      // Recording refinement
    currentTime < 11 ? 'processing' :    // Processing
    'complete';                          // Refined response complete

  const recordingSeconds = widgetState === 'recording' 
    ? Math.floor(currentTime - 4.5) 
    : 0;

  // Progressive text reveal for refinement request
  const displayedRefinementRequest = widgetState === 'recording' && recordingSeconds > 0
    ? refinementRequest.slice(0, Math.min(refinementRequest.length, recordingSeconds * 20))
    : widgetState === 'processing' || (widgetState === 'complete' && isRefining) 
      ? refinementRequest 
      : "";

  // Request text changes during refinement
  const displayedRequest = isRefining ? displayedRefinementRequest : initialRequest;

  // Output text - stream the refined response after processing
  const displayedOutput = (() => {
    if (!isRefining) return initialResponse;
    if (widgetState === 'recording' || widgetState === 'processing') return initialResponse;
    // Stream refined response
    const streamTime = currentTime - 11;
    const charsPerSecond = 100;
    const chars = Math.floor(streamTime * charsPerSecond);
    return refinedResponse.slice(0, Math.min(chars, refinedResponse.length));
  })();

  return (
    <div className="relative w-full h-full grid grid-cols-2 gap-4 p-4">
      {/* Left: Email context */}
      <div 
        className={`transition-opacity duration-500 ${
          isDrawing ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <EmailContext />
      </div>

      {/* Right: AssistantSession Widget */}
      <div className="flex items-start justify-center pt-4">
        {showWidget && (
          <div className="relative">
            <AssistantSessionWidgetMock
              state={widgetState}
              requestText={displayedRequest}
              suggestionOutput={displayedOutput}
              recordingSeconds={recordingSeconds}
              expandOutput={true}
            />
            
            {/* Refine button highlight overlay */}
            {showRefineHighlight && (
              <div className="absolute bottom-14 right-16 pointer-events-none">
                <div className="animate-pulse bg-blue-400/30 rounded-lg px-4 py-2 border-2 border-blue-500">
                  <span className="text-xs text-blue-700 font-medium">Click to refine →</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Refinement info - positioned at bottom center */}
      {isRefining && currentTime < 11 && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-white px-4 py-3 rounded-lg shadow-lg border border-gray-200">
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-sm text-gray-600">
            {widgetState === 'recording' ? 'Recording refinement...' : 'Improving response...'}
          </span>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// ONBOARDING DEMO COMPONENT
// ============================================================================

interface OnboardingDemoProps {
  config: OnboardingDemoConfig;
}

const OnboardingDemo: React.FC<OnboardingDemoProps> = ({ config }) => {
  const isAgentTask = config.mode === 'agentTask';
  const isAssistantSessionText = config.mode === 'assistantSession-text';
  
  // Filter use cases based on mode and optional filter
  const availableCases = useMemo(() => {
    const baseCases = isAgentTask ? MINION_CASES : ASSISTANT_SESSION_CASES;
    if (config.showUseCases && config.showUseCases.length > 0) {
      return baseCases.filter(uc => config.showUseCases!.includes(uc.id));
    }
    return baseCases;
  }, [isAgentTask, config.showUseCases]);

  // Determine default selection
  const defaultId = config.defaultUseCase && availableCases.some(uc => uc.id === config.defaultUseCase)
    ? config.defaultUseCase
    : availableCases[0]?.id || '';

  const [selectedId, setSelectedId] = useState<string>(defaultId);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [hasStartedDrawing, setHasStartedDrawing] = useState(false);
  const [demoPhase, setDemoPhase] = useState<'waiting' | 'transcribing' | 'playing' | 'complete'>('waiting');
  // Only wait for Swift if autoStart is explicitly false
  const [waitingForSwift, setWaitingForSwift] = useState(config.autoStart === false);
  const animationRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Register Swift bridge callbacks
  useEffect(() => {
    swiftBridge.onDemoStart = () => {
      setWaitingForSwift(false);
      setDemoPhase('playing');
      playAnimation();
    };
    
    // Update Swift bridge state getter
    if ((window as any).basilDemoControl) {
      (window as any).basilDemoControl.getState = () => ({
        isPlaying,
        currentPhase: demoPhase,
        currentTime,
      });
    }
    
    return () => {
      swiftBridge.onDemoStart = undefined;
    };
  }, [isPlaying, demoPhase, currentTime]);

  // Notify Swift of phase changes
  useEffect(() => {
    swiftBridge.onDemoPhaseChange?.(demoPhase);
    if (demoPhase === 'complete') {
      swiftBridge.onDemoComplete?.();
    }
  }, [demoPhase]);

  // Get selected case
  const selectedCase = availableCases.find(uc => uc.id === selectedId) || availableCases[0];

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
    // Cancel flow: widget dismisses at 7.5s, add small buffer
    if (config.showCancel) {
      return 8;
    }
    // Refine flow: check if it has a duration
    if (config.showRefine) {
      return 14; // Refine flow typically takes ~14 seconds
    }
    if (isAgentTask && selectedCase) {
      return (selectedCase as AgentTaskUseCase).duration;
    }
    // Typed-AssistantSession entry: calculate based on actual content timing
    if (isAssistantSessionText && selectedCase) {
      const ftCase = selectedCase as UseCase;
      // Match the timing logic of the typed-AssistantSession entry path
      const typingStartTime = 3.5;
      const charsPerSecond = 20;
      const typingDuration = Math.max(3, ftCase.requestText.length / charsPerSecond);
      const postTypingPause = 0.5;
      const transitionTime = typingStartTime + typingDuration + postTypingPause;
      const processingDuration = 5;
      const outputStartTime = transitionTime + processingDuration;
      const streamCharsPerSecond = 60;
      const streamingDuration = ftCase.outputText.length / streamCharsPerSecond;
      // Add 2s buffer for viewing the complete result
      return outputStartTime + streamingDuration + 2;
    }
    // AssistantSession
    if (selectedCase && !isAgentTask) {
      const vsCase = selectedCase as UseCase;
      const streamStartTime = 11;
      const charsPerSecond = 80;
      const streamingTime = vsCase.outputText.length / charsPerSecond;
      return streamStartTime + streamingTime + 1;
    }
    return 16;
  }, [isAgentTask, isAssistantSessionText, selectedCase, config.showCancel, config.showRefine]);

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

  // Auto-play on mount (unless waiting for Swift or explanation not dismissed)
  useEffect(() => {
    if (waitingForSwift) {
      // Wait for Swift to call startDemo
      console.log('[OnboardingDemo] Waiting for Swift to start demo...');
      return;
    }
    
    // Handle transcription delay if configured
    const delay = config.transcriptionDuration 
      ? (config.transcriptionDuration * 1000) + 300 
      : 300;
    
    const timer = setTimeout(() => {
      setDemoPhase('playing');
      playAnimation();
    }, delay);
    return () => clearTimeout(timer);
  }, [playAnimation, waitingForSwift, config.transcriptionDuration]);

  // Update phase when animation completes
  useEffect(() => {
    if (!isPlaying && currentTime >= minDuration && currentTime > 0) {
      setDemoPhase('complete');
    }
  }, [isPlaying, currentTime, minDuration]);

  return (
    <div ref={containerRef} className="w-full h-full flex flex-col bg-transparent">
      {/* Waiting state for Swift synchronization */}
      {waitingForSwift && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/20 rounded-xl z-10">
          <div className="text-center text-white">
            <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin mx-auto mb-2" />
            <p className="text-sm opacity-80">Preparing demo...</p>
          </div>
        </div>
      )}
      
      {/* Use Case Selector - Only show for general demos, not specific action demos */}
      {availableCases.length > 1 && !config.showCancel && !config.showRefine && (
        <div className="mb-1 px-4 overflow-hidden">
          <div className="flex items-center gap-2 overflow-x-auto scrollbar-hide px-1 py-0.5">
            {availableCases.map((item) => (
            <button
                key={item.id}
                onClick={() => handleSelectCase(item.id)}
              className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap
                transition-all duration-300 shrink-0
                  ${selectedId === item.id
                    ? 'bg-emerald-600 text-white shadow-md shadow-emerald-500/20 scale-[1.02]'
                    : 'bg-white/80 text-gray-700 hover:bg-white border border-gray-200/80'
                }
              `}
            >
                {item.icon}
                <span>{item.label}</span>
            </button>
            ))}
          </div>
        </div>
      )}

      {/* Demo Panel */}
      <div 
        className="relative flex-1 rounded-xl border border-gray-700/50 shadow-lg p-3 sm:p-4 min-h-[432px] bg-cover bg-center overflow-hidden"
        style={{ backgroundImage: "url('../../images/home/Desktop_Background.jpg')" }}
      >
        {/* Specific demo flows */}
        {config.showCancel ? (
          <CancelFlowDemo currentTime={currentTime} isDrawing={hasStartedDrawing} />
        ) : config.showRefine ? (
          <RefineFlowDemo currentTime={currentTime} isDrawing={hasStartedDrawing} />
        ) : isAgentTask && selectedCase ? (
          <AgentTaskPanel 
            useCase={selectedCase as AgentTaskUseCase}
            currentTime={currentTime} 
            isDrawing={hasStartedDrawing}
          />
        ) : isAssistantSessionText && selectedCase ? (
          // Typed-AssistantSession mode (input_modality = "text"). The dedicated
          // panel was removed during AssistantSession Phase 1; this branch renders
          // nothing until a follow-up rebuild wires the typed entry path
          // into the unified AssistantSession pipeline. Until then, Swift falls
          // back to a static skeleton for this onboarding step.
          null
        ) : selectedCase ? (
          <AssistantSessionPanel
            useCase={selectedCase as UseCase}
            currentTime={currentTime}
            isDrawing={hasStartedDrawing}
          />
        ) : null}
        
        {/* Voice Transcription Overlay - positioned at very bottom of demo container */}
        {(() => {
          // Skip for refine flows and the typed-AssistantSession entry (no speech phase)
          if (config.showRefine || isAssistantSessionText) return null;
          
          // Cancel flow: custom staged transcription with deliberate pause before *Presses Esc*
          // Timeline: 0.5-5.3s speaking (4.8s, slowed by 20%), 5.3-7.25s pause (1.95s, increased by 30%), 7.25s+ shows *Presses Esc*
          // Transcription remains visible after demo completes so users can see what was said
          if (config.showCancel) {
            // Keep transcription visible once it starts (no time limit)
            const isVisible = hasStartedDrawing && currentTime >= 0.5;
            const showEscText = currentTime >= 7.25;
            const isRecording = currentTime >= 0.5 && currentTime < 7.25; // Stop pulsing after Esc is pressed
            
            if (!isVisible) return null;
            
            // Custom cancel transcription overlay with staged reveal
            // Split text at "No" to add deliberate pauses before and after it appears
            const textBeforeNo = "Actually, cross-reference column G with the normalised satisfaction scores and—";
            const justNo = "No.";
            const textAfterNoPause = "They've seen the spreadsheet. They're not ready for the pivot table.";
            const wordsBeforeNo = textBeforeNo.split(' ').filter(w => w.length > 0);
            const wordsAfterNoPause = textAfterNoPause.split(' ').filter(w => w.length > 0);
            
            // Timing: reveal first part over 3.2s, pause for 0.8s, reveal "No.", pause 0.8s again, then reveal rest
            const firstPartDuration = 3.2; // Time to reveal text before "No"
            const pauseBeforeNo = 0.8; // Pause before "No" appears
            const noRevealDuration = 0.1; // Very quick reveal for "No." itself
            const pauseAfterNo = 0.8; // Pause after "No." before next sentence (comparable to first pause)
            const finalPartDuration = 0.8; // Time to reveal final sentence
            
            const elapsed = currentTime - 0.5;
            let visibleText = '';
            
            if (elapsed < firstPartDuration) {
              // Reveal first part
              const progress = elapsed / firstPartDuration;
              const wordsToShow = Math.floor(progress * wordsBeforeNo.length);
              visibleText = wordsBeforeNo.slice(0, wordsToShow).join(' ');
            } else if (elapsed < firstPartDuration + pauseBeforeNo) {
              // Pause - show first part fully, but not "No" yet
              visibleText = textBeforeNo;
            } else if (elapsed < firstPartDuration + pauseBeforeNo + noRevealDuration) {
              // Reveal "No." quickly
              visibleText = textBeforeNo + ' ' + justNo;
            } else if (elapsed < firstPartDuration + pauseBeforeNo + noRevealDuration + pauseAfterNo) {
              // Pause after "No." - show first part + "No." but not the final sentence yet
              visibleText = textBeforeNo + ' ' + justNo;
            } else {
              // Reveal final sentence
              const finalPartElapsed = elapsed - (firstPartDuration + pauseBeforeNo + noRevealDuration + pauseAfterNo);
              const progress = Math.min(1, finalPartElapsed / finalPartDuration);
              const wordsToShow = Math.floor(progress * wordsAfterNoPause.length);
              visibleText = textBeforeNo + ' ' + justNo + ' ' + wordsAfterNoPause.slice(0, wordsToShow).join(' ');
              
              // After final part is complete, always show full text
              if (progress >= 1) {
                visibleText = textBeforeNo + ' ' + justNo + ' ' + textAfterNoPause;
              }
            }
            
            // Split text to make "No" italic
            const renderTextWithItalicNo = (text: string) => {
              // Check if "No" appears in the text
              const noIndex = text.indexOf('No.');
              if (noIndex === -1) {
                return text;
              }
              
              // Split at "No." and wrap it in italic
              const beforeNo = text.substring(0, noIndex);
              const afterNo = text.substring(noIndex + 3); // Skip "No."
              
              return (
                <>
                  {beforeNo}
                  <span className="italic">No.</span>
                  {afterNo}
                </>
              );
            };
            
            return (
              <div 
                className="absolute bottom-0 left-0 right-0 flex items-center gap-3 px-4 py-3 bg-white/95 backdrop-blur-sm shadow-lg border-t border-blue-200/50"
              >
                {/* Microphone indicator - stops pulsing after recording ends */}
                <div className="relative flex-shrink-0">
                  {isRecording && (
                    <div 
                      className="absolute inset-0 bg-blue-500/30 rounded-full animate-pulse"
                    />
                  )}
                  <div className="relative w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center">
                    <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-white" fill="currentColor">
                      <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                      <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                    </svg>
                  </div>
                </div>

                {/* Transcription text */}
                <p className="text-sm text-gray-800 leading-snug flex-1">
                  {renderTextWithItalicNo(visibleText)}
                  {/* *Presses Esc* appears after the pause, styled distinctly */}
                  {showEscText && (
                    <span 
                      className="ml-2 text-gray-500 italic transition-opacity duration-300"
                      style={{ opacity: showEscText ? 1 : 0 }}
                    >
                      *Presses Esc*
                    </span>
                  )}
                </p>
              </div>
            );
          }
          
          // For AssistantSessions: calculate dynamic reveal rate to fit in recording window (3s to 7s)
          const vsText = (selectedCase as UseCase)?.requestText || '';
          const vsWordCount = vsText.split(' ').filter((w: string) => w.length > 0).length;
          const vsChunks = Math.ceil(vsWordCount / 3);
          const vsRevealTime = 3.5;
          const vsChunksPerSecond = Math.max(2.5, vsChunks / vsRevealTime);
          
          // For AgentTasks: use AgentTask text
          const vcCase = selectedCase as AgentTaskUseCase;
          const vcText = vcCase?.agentTaskText || '';
          const vcWordCount = vcText.split(' ').filter((w: string) => w.length > 0).length;
          const vcChunks = Math.ceil(vcWordCount / 3);
          const vcChunksPerSecond = Math.max(2.5, vcChunks / 3.5);
          
          // Determine visibility
          // Don't show transcription for text-entry mode use cases
          const isAssistantSessionRecording = !isAgentTask && hasStartedDrawing && currentTime >= 3 && currentTime < 7;
          const isAgentTaskCapture = isAgentTask && hasStartedDrawing && vcCase?.getPhase?.(currentTime) === 'capture' && !vcCase?.isTextEntryMode;
          
          return (
            <VoiceTranscriptionOverlay
              transcriptText={isAgentTask ? vcText : vsText}
              isVisible={isAssistantSessionRecording || isAgentTaskCapture}
              chunksPerSecond={isAgentTask ? vcChunksPerSecond : vsChunksPerSecond}
            />
          );
        })()}
      </div>

      {/* Replay control - compact - always reserve space to prevent layout shift */}
      <div className="text-center mt-2 min-h-[20px] flex items-center justify-center">
        <p className="text-xs text-gray-600">
          {isPlaying ? (
            <span className="flex items-center justify-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Playing...
            </span>
          ) : currentTime > 0 ? (
            <button 
              onClick={playAnimation}
              className="text-emerald-600 hover:text-emerald-500 transition-colors flex items-center justify-center gap-1 mx-auto"
            >
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
              Replay
            </button>
          ) : (
            // Invisible placeholder to reserve space when nothing is shown
            <span className="invisible">Playing...</span>
          )}
        </p>
      </div>
    </div>
  );
};

// ============================================================================
// MOUNT
// ============================================================================

const config = getConfig();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {/*
      h-full (not h-screen) is intentional. The page is loaded inside a
      WKWebView whose frame is sized by SwiftUI (.frame(maxHeight: .infinity)
      in EnhancedDemoContainerView), and `100vh` in WKWebView tracks the
      layout viewport, which can diverge from the actual NSView bounds —
      so `h-screen` would produce a wrapper that's taller or shorter than
      the visible WebView area, leaving the demo panel either clipped or,
      more often, finishing well above the bottom of the WebView and
      showing as an empty band beneath the cityscape background.

      The hosting HTML sets up an explicit height chain (html, body, #root
      all `height: 100%`), so `h-full` here resolves through that chain to
      exactly the WebView's frame height. Combined with the inner
      `flex flex-col` + `flex-1` on the demo panel, the panel now expands
      to fill all space between the use-case selectors and the replay
      control instead of stopping at its `min-h-[432px]` floor.
    */}
    <div className="w-full h-full bg-transparent p-2">
      <OnboardingDemo config={config} />
    </div>
  </React.StrictMode>,
);

export default OnboardingDemo;
