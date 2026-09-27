"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  MockEmailWindow,
  MockBrowserWindow,
  MockChatInterface,
  StepCounter,
  DrawingPanel,
  DrawingWindow,
  BasilWireframeWrapper,
  AnimatedStepLabel,
} from '../shared';
import AssistantSessionWidgetMock from './AssistantSessionWidgetMock';

interface WorkflowComparisonProps {
  className?: string;
}

/**
 * WorkflowComparison - Orchestrates the Before/After animation comparing
 * the ChatGPT copy-paste workflow vs Basil's AssistantSession approach.
 * 
 * Features SVG stroke-drawing animation for panel construction (Stripe-style).
 */

// Old Way steps - includes style/tone revision that Basil handles automatically
// Extended timeline with realistic typing simulation
const OLD_WAY_STEPS = [
  { time: 2, label: "Read the email" },
  { time: 5, label: "Copy the email content" },
  { time: 8, label: "Open browser" },
  { time: 11, label: "Navigate to ChatGPT" },
  { time: 14, label: "Paste email into chat" },
  { time: 17, label: "Typing prompt..." },
  { time: 22, label: "Wait for response..." },
  { time: 28, label: "Response too formal..." },
  { time: 31, label: "Typing revision request..." },
  { time: 38, label: "Wait for revision..." },
  { time: 44, label: "Copy the revised response" },
  { time: 47, label: "Paste into email" },
];

// Basil steps - knows your style from local profile, no revisions needed
const BASIL_STEPS = [
  { time: 2, label: "Double-tap ⌥ and speak" },
  { time: 8, label: "Done — pasted directly to email" },
];

const OLD_WAY_COMPLETE_TIME = 47;
const BASIL_COMPLETE_TIME = 8;
const TOTAL_DURATION = 55; // 47s animation + 8s pause

// Email reply content - friendly tone that matches user's style
const EMAIL_REPLY_TEXT = `Hi Julia,

Thanks for following up! I really enjoyed our conversation as well and I'm equally excited about the possibilities.

Tuesday works perfectly for me. I'm free between 10am and 2pm ET - let me know what time works best for you.

Looking forward to diving deeper into the integration details.

Best,
Sam`;

// Fade duration for loop transition
const FADE_DURATION = 1.5; // seconds

const WorkflowComparison = ({ className = "" }: WorkflowComparisonProps) => {
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasStartedDrawing, setHasStartedDrawing] = useState(false);
  const [isFadingOut, setIsFadingOut] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);

  // Trigger drawing animation when component comes into view
  useEffect(() => {
    if (isPlaying && !hasStartedDrawing) {
      setHasStartedDrawing(true);
    }
  }, [isPlaying, hasStartedDrawing]);

  // Calculate current step for Old Way
  const getOldWayStep = useCallback((time: number): number => {
    for (let i = OLD_WAY_STEPS.length - 1; i >= 0; i--) {
      const step = OLD_WAY_STEPS[i];
      if (step && time >= step.time) return i + 1;
    }
    return 0;
  }, []);

  // Calculate current step for Basil
  const getBasilStep = useCallback((time: number): number => {
    for (let i = BASIL_STEPS.length - 1; i >= 0; i--) {
      const step = BASIL_STEPS[i];
      if (step && time >= step.time) return i + 1;
    }
    return 0;
  }, []);

  // Derived state
  const oldWayStep = getOldWayStep(currentTime);
  const basilStep = getBasilStep(currentTime);
  const isBasilComplete = currentTime >= BASIL_COMPLETE_TIME;
  const isOldWayComplete = currentTime >= OLD_WAY_COMPLETE_TIME;

  // Stopwatch times - Basil's freezes when complete
  const basilElapsedTime = isBasilComplete ? BASIL_COMPLETE_TIME : Math.max(0, currentTime);
  const oldWayElapsedTime = isOldWayComplete ? OLD_WAY_COMPLETE_TIME : Math.max(0, currentTime);

  // Format time as MM:SS
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Animation states for Old Way chat interface
  // Extended timeline with typing simulation
  const chatAnimationStep = 
    currentTime < 14 ? 0 :   // Nothing in chat yet
    currentTime < 17 ? 1 :   // Email pasted
    currentTime < 22 ? 2 :   // Typing prompt (extended for realism)
    currentTime < 28 ? 3 :   // AI loading
    currentTime < 31 ? 4 :   // First response (too formal)
    currentTime < 38 ? 6 :   // User types revision request (extended)
    currentTime < 44 ? 7 :   // AI loading revision
    currentTime < 47 ? 8 :   // Revised response shown
    9;                        // Final - response copied

  // Show browser when navigating (at 8s)
  const showBrowser = currentTime >= 8;
  
  // Show reply in old way email (when complete)
  const showOldWayReply = currentTime >= OLD_WAY_COMPLETE_TIME;

  // Animation states for Basil AssistantSession
  // idle -> recording -> processing (green bubble) -> complete (blue)
  const basilState: 'idle' | 'recording' | 'processing' | 'complete' =
    currentTime < 3 ? 'idle' :
    currentTime < 7 ? 'recording' :
    currentTime < 8 ? 'processing' :  // Green bubble while generating
    'complete';
  
  // Recording timer
  const recordingSeconds = useMemo(() => {
    if (basilState === 'recording') {
      return Math.floor(currentTime - 3);
    }
    return 0;
  }, [basilState, currentTime]);
  
  // Request text - gradual reveal during recording
  const basilRequestText = currentTime >= 6 
    ? "Draft a friendly reply, I'm free Tuesday between 10 and 2" 
    : currentTime >= 5 
    ? "Draft a friendly reply, I'm free Tuesday..." 
    : currentTime >= 4 
    ? "Draft a friendly reply..." 
    : "";

  // Show suggestion output when complete (at 8s)
  const showSuggestionOutput = currentTime >= 8;

  // Intersection Observer
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
            setIsPlaying(true);
          }
        });
      },
      { threshold: 0.5 }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, []);

  // Animation loop
  useEffect(() => {
    if (!isPlaying || isFadingOut) return;

    const animate = (timestamp: number) => {
      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
      }

      const delta = (timestamp - lastTimeRef.current) / 1000;
      lastTimeRef.current = timestamp;

      setCurrentTime((prev) => {
        const next = prev + delta;
        // Start fade out when we reach the end
        if (next >= TOTAL_DURATION - FADE_DURATION && !isFadingOut) {
          setIsFadingOut(true);
          return prev; // Stop incrementing during fade
        }
        return next;
      });

      animationRef.current = requestAnimationFrame(animate);
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isPlaying, isFadingOut]);

  // Handle the fade out and reset
  useEffect(() => {
    if (!isFadingOut) return;
    
    // Wait for fade to complete, then reset
    const timer = setTimeout(() => {
      setCurrentTime(0);
      setHasStartedDrawing(false);
      lastTimeRef.current = 0;
      
      // Small delay before starting the fade-in and new animation
      setTimeout(() => {
        setIsFadingOut(false);
        setHasStartedDrawing(true);
      }, 100);
    }, FADE_DURATION * 1000);
    
    return () => clearTimeout(timer);
  }, [isFadingOut]);

  return (
    <div ref={containerRef} className={`py-16 ${className}`}>
      {/* Section Header */}
      <div className="text-center mb-10 sm:mb-14 px-4">
        <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-gray-900 mb-3 sm:mb-4">
          The current way of interacting with AI{' '}
          <span className="text-red-500 italic relative inline-block">
            sucks
            {/* Sparkle particles */}
            <svg className="sparkle sparkle-1" viewBox="0 0 24 24" fill="none">
              <path d="M12 0L14 10L24 12L14 14L12 24L10 14L0 12L10 10L12 0Z" fill="#f59e0b"/>
            </svg>
            <svg className="sparkle sparkle-2" viewBox="0 0 24 24" fill="none">
              <path d="M12 0L14 10L24 12L14 14L12 24L10 14L0 12L10 10L12 0Z" fill="#fb923c"/>
            </svg>
            <svg className="sparkle sparkle-3" viewBox="0 0 24 24" fill="none">
              <path d="M12 0L14 10L24 12L14 14L12 24L10 14L0 12L10 10L12 0Z" fill="#fbbf24"/>
            </svg>
            <svg className="sparkle sparkle-4" viewBox="0 0 24 24" fill="none">
              <path d="M12 0L14 10L24 12L14 14L12 24L10 14L0 12L10 10L12 0Z" fill="#f97316"/>
            </svg>
          </span>.
        </h2>
        <p className="text-base sm:text-lg lg:text-xl text-gray-600 max-w-2xl mx-auto">
          Copy. Paste. Wait. Copy. Paste. Wait. No, not like that, stupid. Yell at the AI. Contemplate our inexorable march towards death. Copy. Paste....
        </p>
      </div>

      {/* Comparison Grid - fades out/in on loop */}
      <div 
        className="max-w-5xl mx-auto px-4 transition-opacity duration-1000 ease-in-out"
        style={{ opacity: isFadingOut ? 0 : 1 }}
      >
        <div className="grid grid-cols-2 gap-8 lg:gap-12">
          
          {/* Left Panel - Old Way */}
          <div className="space-y-3">
            {/* Header: Title centered, step counter top-right */}
            <div className="flex items-center justify-between mb-2">
              <div className="w-24" />
              <h3 className="text-lg sm:text-xl font-semibold text-gray-700">The ChatGPT Shuffle</h3>
              <div className="w-24 flex justify-end">
                <StepCounter 
                  current={oldWayStep || 1} 
                  total={12} 
                  isComplete={isOldWayComplete}
                />
              </div>
            </div>
            
            {/* Drawing Panel */}
            <DrawingPanel isDrawing={hasStartedDrawing} variant="gray">
              {/* Email Window with wireframe */}
              <div className="absolute top-2 left-2" style={{ transform: 'scale(0.58)', transformOrigin: 'top left' }}>
                <DrawingWindow isDrawing={hasStartedDrawing} delay={1.5} variant="gray">
                  <MockEmailWindow
                    showReply={showOldWayReply}
                    replyText={showOldWayReply ? EMAIL_REPLY_TEXT : ""}
                    scale={1}
                    instant={true}
                  />
                </DrawingWindow>
              </div>
              
              {/* Browser Window with wireframe - larger scale */}
              <div 
                className={`absolute top-2 right-2 transition-all duration-1000 ease-out origin-top-right ${
                  showBrowser ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'
                }`}
                style={{ transform: 'scale(0.88)', transformOrigin: 'top right' }}
              >
                <DrawingWindow isDrawing={showBrowser} delay={0} variant="blue">
                  <MockBrowserWindow isVisible={showBrowser} scale={1}>
                    <MockChatInterface 
                      animationStep={chatAnimationStep} 
                      isEmailReply 
                      showRevisionFlow={true}
                    />
                  </MockBrowserWindow>
                </DrawingWindow>
              </div>
            </DrawingPanel>
            
            {/* Step label - centered */}
            <div className="text-center pt-1">
              <AnimatedStepLabel 
                steps={OLD_WAY_STEPS} 
                currentStep={oldWayStep || 1} 
              />
            </div>
          </div>

          {/* Right Panel - Basil Way */}
          <div className="space-y-3">
            {/* Header: Title centered, step counter top-right */}
            <div className="flex items-center justify-between mb-2">
              <div className="w-24" />
              <h3 className="text-lg sm:text-xl font-semibold text-green-700">With Basil</h3>
              <div className="w-24 flex justify-end">
                <StepCounter 
                  current={basilStep || 1} 
                  total={2} 
                  isComplete={isBasilComplete}
                />
              </div>
            </div>
            
            {/* Drawing Panel */}
            <DrawingPanel isDrawing={hasStartedDrawing} variant="green">
              {/* Email Window with wireframe - same scale as ChatGPT side */}
              <div className="absolute top-2 left-2" style={{ transform: 'scale(0.58)', transformOrigin: 'top left' }}>
                <DrawingWindow isDrawing={hasStartedDrawing} delay={1.5} variant="gray">
                  <MockEmailWindow
                    showReply={isBasilComplete}
                    replyText={isBasilComplete ? EMAIL_REPLY_TEXT : ""}
                    scale={1}
                    instant={true}
                  />
                </DrawingWindow>
              </div>
              
              {/* AssistantSession Widget with wireframe */}
              <div 
                className={`absolute top-2 right-2 transition-all duration-700 ease-out origin-top-right ${
                  currentTime >= 2 ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'
                }`}
                style={{ transform: 'scale(0.85)', transformOrigin: 'top right' }}
              >
                <BasilWireframeWrapper 
                  isDrawing={currentTime >= 2} 
                  isComplete={showSuggestionOutput}
                >
                  <AssistantSessionWidgetMock
                    state={basilState}
                    requestText={basilRequestText}
                    suggestionOutput={showSuggestionOutput ? EMAIL_REPLY_TEXT : ""}
                    recordingSeconds={recordingSeconds}
                  />
                </BasilWireframeWrapper>
              </div>
              
              {/* "Done" badge */}
              {isBasilComplete && (
                <div 
                  className="absolute bottom-2 right-2 flex items-center gap-1.5 sm:gap-2 bg-green-100 text-green-700 px-2.5 sm:px-3 py-1.5 rounded-full text-xs sm:text-sm font-medium shadow-sm"
                  style={{ animation: 'pulse 2s ease-in-out infinite' }}
                >
                  <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  Pasted at cursor
                </div>
              )}
            </DrawingPanel>
            
            {/* Step label - centered */}
            <div className="text-center pt-1">
              <AnimatedStepLabel 
                steps={BASIL_STEPS} 
                currentStep={basilStep || 1} 
              />
            </div>
          </div>
        </div>

        {/* Comparison Summary - visible immediately, counts tick up */}
        <div 
          className={`mt-10 sm:mt-14 text-center transition-all duration-700 relative ${
            hasStartedDrawing ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
          }`}
        >
          <div className="inline-flex items-center gap-4 sm:gap-8 bg-white rounded-2xl px-5 sm:px-8 py-4 sm:py-5 shadow-xl border-2 border-gray-300">
            {/* Old Way stats */}
            <div className="text-center">
              <div className="text-2xl sm:text-3xl font-bold text-red-500 tabular-nums transition-all duration-200">
                {oldWayStep}
              </div>
              <div className="text-xs text-gray-500">steps</div>
            </div>
            <div className="text-center border-l border-gray-200 pl-4 sm:pl-8">
              <div className="text-2xl sm:text-3xl font-bold text-red-500 font-mono tabular-nums transition-all duration-200">
                {formatTime(oldWayElapsedTime)}
              </div>
              <div className="text-xs text-gray-500">elapsed</div>
            </div>
            
            <div className="text-xl sm:text-2xl text-gray-300 font-light px-2">vs</div>
            
            {/* Basil stats */}
            <div className="text-center border-r border-gray-200 pr-4 sm:pr-8">
              <div className={`text-2xl sm:text-3xl font-bold font-mono tabular-nums transition-all duration-200 ${
                isBasilComplete ? 'text-green-500' : 'text-green-400'
              }`}>
                {formatTime(basilElapsedTime)}
              </div>
              <div className="text-xs text-gray-500">elapsed</div>
            </div>
            <div className="text-center">
              <div className={`text-2xl sm:text-3xl font-bold tabular-nums transition-all duration-200 ${
                isBasilComplete ? 'text-green-500' : 'text-green-400'
              }`}>
                {basilStep}
              </div>
              <div className="text-xs text-gray-500">steps</div>
            </div>
          </div>
          
          {/* Time savings callout - always present, fades in once animation starts */}
          <div 
            className={`absolute left-0 right-0 top-full mt-3 text-sm text-gray-600 transition-opacity duration-500 ${
              currentTime > 0 ? 'opacity-100' : 'opacity-0'
            }`}
          >
            {isOldWayComplete ? (
              <span className="text-green-600 font-medium">...anyway.</span>
            ) : !isBasilComplete ? (
              <span>And off they go.</span>
            ) : currentTime < 11 ? (
              <span>Oh.</span>
            ) : currentTime < 18 ? (
              <span>This is fine.</span>
            ) : currentTime < 26 ? (
              <span>Don't worry Rocky, take your time.</span>
            ) : (
              <span>What is it with this guy?</span>
            )}
          </div>
        </div>
      </div>
      
      {/* CSS for animations */}
      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.85; transform: scale(1.02); }
        }
        
        .sparkle {
          position: absolute;
          width: 12px;
          height: 12px;
          pointer-events: none;
          filter: drop-shadow(0 0 3px #f59e0b);
        }
        .sparkle-1 {
          top: -1px;
          right: 4px;
          animation: twinkle 1.2s ease-in-out infinite;
        }
        .sparkle-2 {
          top: 35%;
          left: -6px;
          width: 9px;
          height: 9px;
          animation: twinkle 1.4s ease-in-out 0.3s infinite;
        }
        .sparkle-3 {
          bottom: 0px;
          right: 30%;
          width: 10px;
          height: 10px;
          animation: twinkle 1s ease-in-out 0.6s infinite;
        }
        .sparkle-4 {
          top: 1px;
          left: 20%;
          width: 7px;
          height: 7px;
          animation: twinkle 1.5s ease-in-out 0.9s infinite;
        }
        @keyframes twinkle {
          0%, 100% {
            opacity: 0;
            transform: scale(0.3) rotate(0deg);
          }
          50% {
            opacity: 1;
            transform: scale(1.1) rotate(20deg);
          }
        }
      `}</style>
    </div>
  );
};

export default WorkflowComparison;
