"use client";

import { useState, useEffect, useMemo } from 'react';
import { BasilWireframeWrapper, DrawingWindow, SimulatedMenuBar } from '../shared';
import AssistantSessionWidgetMock from './AssistantSessionWidgetMock';
import { IMessageContext, SlackContext, UseCase } from './contexts';

interface AssistantSessionPanelProps {
  /** The use case to render */
  useCase: UseCase;
  /** Current animation time in seconds */
  currentTime: number;
  /** Whether drawing animation has started */
  isDrawing: boolean;
}

/**
 * AssistantSessionPanel - Generic panel for rendering any AssistantSession use case.
 * Handles state transitions: idle → recording → processing → complete.
 */
const AssistantSessionPanel = ({
  useCase,
  currentTime,
  isDrawing,
}: AssistantSessionPanelProps) => {
  // Animation states with slower pacing
  // idle -> recording -> processing (green) -> complete (blue)
  const basilState: 'idle' | 'recording' | 'processing' | 'complete' = 
    currentTime < 3 ? 'idle' :
    currentTime < 7 ? 'recording' :
    currentTime < 11 ? 'processing' :
    'complete';

  const recordingSeconds = basilState === 'recording' ? Math.floor(currentTime - 3) : 0;

  // Progressive request text reveal during recording
  const requestProgress = Math.min(1, Math.max(0, (currentTime - 3.5) / 3.5));
  const displayedRequest = useCase.requestText.slice(
    0, 
    Math.floor(useCase.requestText.length * requestProgress)
  );

  const showOutput = currentTime >= 11;

  // Streaming output - progressively reveal text after showOutput becomes true
  const { streamedOutput, isStreamingText } = useMemo(() => {
    if (!showOutput) return { streamedOutput: "", isStreamingText: false };
    
    const fullOutput = useCase.outputText;
    const streamStartTime = 11;
    const elapsed = currentTime - streamStartTime;
    
    // Stream at ~80 characters per second
    const charsPerSecond = 80;
    const charsToShow = Math.floor(elapsed * charsPerSecond);
    const sliced = fullOutput.slice(0, Math.min(charsToShow, fullOutput.length));
    
    return { 
      streamedOutput: sliced, 
      isStreamingText: sliced.length < fullOutput.length 
    };
  }, [showOutput, useCase.outputText, currentTime]);

  // Track when streaming completes
  const [streamingComplete, setStreamingComplete] = useState(false);
  
  useEffect(() => {
    if (showOutput && !isStreamingText) {
      setStreamingComplete(true);
    }
  }, [showOutput, isStreamingText]);

  // Reset streaming state when use case changes or animation restarts
  useEffect(() => {
    setStreamingComplete(false);
  }, [useCase.id, isDrawing]);

  // Keep bubble green while streaming, only turn blue when done
  const effectiveState = (showOutput && !streamingComplete) 
    ? 'processing' 
    : basilState;

  // Context fades in first, then widget
  const showContext = currentTime >= 1;
  const showWidget = currentTime >= 2.5;
  
  // Recording state for menu bar
  const isRecording = basilState === 'recording';

  return (
    <div className="relative flex flex-col h-full">
      {/* Simulated Menu Bar - edge to edge */}
      <SimulatedMenuBar isRecording={isRecording} />
      
      {/* Main content area with padding */}
      <div className="flex-1 grid grid-cols-2 gap-4 sm:gap-6 p-4 sm:p-6">
      {/* Left: Context Window */}
      <div 
        className={`transition-all duration-700 ease-out ${
          showContext ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-8'
        }`}
      >
        <DrawingWindow 
          key={`context-${useCase.id}-${isDrawing}`}
          isDrawing={isDrawing} 
          delay={0.2}
          variant="gray"
        >
          {/* Special handling for text/slack with draft reply */}
          {useCase.id === 'text' ? (
            streamingComplete ? (
              <IMessageContext draftReply={useCase.outputText} />
            ) : (
              <IMessageContext showCursor={basilState === 'recording' || basilState === 'processing' || showOutput} />
            )
          ) : useCase.id === 'slack' ? (
            streamingComplete ? (
              <SlackContext draftReply={useCase.outputText} />
            ) : (
              <SlackContext showCursor={basilState === 'recording' || basilState === 'processing' || showOutput} />
            )
          ) : (
            useCase.contextComponent
          )}
        </DrawingWindow>
      </div>

      {/* Right: AssistantSession Widget */}
      <div 
        className={`flex items-start justify-center transition-all duration-700 ease-out ${
          showWidget ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8'
        }`}
      >
        <BasilWireframeWrapper 
          key={`basil-${useCase.id}-${isDrawing}`}
          isDrawing={isDrawing && showWidget} 
          isComplete={showOutput}
        >
          <AssistantSessionWidgetMock
            state={effectiveState}
            requestText={displayedRequest}
            suggestionOutput={streamedOutput}
            recordingSeconds={recordingSeconds}
            expandOutput={true}
          />
        </BasilWireframeWrapper>
        </div>
      </div>
    </div>
  );
};

export default AssistantSessionPanel;
