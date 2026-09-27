"use client";

import { useState, useEffect } from 'react';
import AnimatedProcessingBubble, { BUBBLE_COLORS } from '../../AnimatedProcessingBubble';

interface AssistantSessionWidgetMockProps {
  state: 'idle' | 'recording' | 'processing' | 'complete';
  requestText?: string;
  suggestionOutput?: string;
  recordingSeconds?: number;
  className?: string;
  expandOutput?: boolean; // When true, allows output to be taller
}

/**
 * AssistantSessionWidgetMock - Faithful reconstruction of the AssistantSessionWidget.
 * Used for context-aware suggestions like email replies, writing help, etc.
 * 
 * Recording state: Shows stop button + timer (like MiniTranscriptionStatusView)
 * Processing state: Shows "Request:" with transcription, ThinkingIndicator
 * Complete state: Shows "Request:" + "Suggestion Output:" + action buttons
 */
const AssistantSessionWidgetMock = ({
  state,
  requestText = "",
  suggestionOutput = "",
  recordingSeconds = 0,
  className = "",
  expandOutput = false,
}: AssistantSessionWidgetMockProps) => {
  const isRecording = state === 'recording';
  const isProcessing = state === 'processing';
  const isComplete = state === 'complete';
  // Show output when complete, OR when processing with content (streaming)
  const showOutput = (isComplete || isProcessing) && suggestionOutput;
  
  // Track seconds for recording display
  const [displaySeconds, setDisplaySeconds] = useState(recordingSeconds);
  
  useEffect(() => {
    setDisplaySeconds(recordingSeconds);
  }, [recordingSeconds]);

  // Format time as MM:SS
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <>

      <div
        className={`relative rounded-2xl bg-white ${className}`}
        style={{
          width: showOutput ? (expandOutput ? 360 : 320) : 240,
          transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Border layers - matching app aesthetic */}
        <div 
          className="absolute inset-0 rounded-2xl pointer-events-none"
          style={{
            border: '1px solid rgba(54, 120, 227, 0.3)',
          }}
        />

        {/* Content */}
        <div className="relative flex flex-col px-3 py-3">
          {/* Header row */}
          <div className="flex items-start justify-between mb-2">
            {/* Left side: close/minimize + icons */}
            <div className="flex items-center gap-1">
              {/* Close button */}
              <div 
                className="w-5 h-5 rounded-full flex items-center justify-center"
                style={{ backgroundColor: 'rgba(54, 120, 227, 0.1)' }}
              >
                <svg className="w-3 h-3" style={{ color: '#6B7280' }} fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </div>
              
              {/* Minimize button */}
              <div 
                className="w-5 h-5 rounded-full flex items-center justify-center"
                style={{ backgroundColor: 'rgba(54, 120, 227, 0.1)' }}
              >
                <svg className="w-3 h-3" style={{ color: '#6B7280' }} fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              
              {/* Brain icon - SF Symbol brain.head.profile.fill */}
              <img 
                src="/images/icons/brain.head.profile.fill.png"
                alt="Brain"
                className="w-4 h-4 ml-1"
                style={{ 
                  filter: 'invert(12%) sepia(70%) saturate(3000%) hue-rotate(210deg) brightness(70%)'
                }}
              />

              {/* Title */}
              <span 
                className="text-[12px] font-medium ml-1"
                style={{ color: '#3678E3' }}
              >
                AssistantSession
              </span>
            </div>

            {/* Animated bubble - with overflow visible for blur effects.
                Bubble colours come from BUBBLE_COLORS so the processing
                pair stays in lockstep with the Swift source of truth via
                the build-time generator. */}
            <div className="relative" style={{ overflow: 'visible' }}>
              <AnimatedProcessingBubble
                size={36}
                isProcessing={isRecording || isProcessing}
                baseColor={(isRecording
                  ? BUBBLE_COLORS.recording
                  : isProcessing
                    ? BUBBLE_COLORS.processing
                    : BUBBLE_COLORS.idle).base}
                accentColor={(isRecording
                  ? BUBBLE_COLORS.recording
                  : isProcessing
                    ? BUBBLE_COLORS.processing
                    : BUBBLE_COLORS.idle).accent}
              />
            </div>
          </div>

        {/* Recording state - Stop button + Timer (matching MiniTranscriptionStatusView) */}
        {isRecording && (
          <div className="mb-2">
            <div 
              className="inline-flex items-center gap-3 px-3 py-2 rounded-lg"
              style={{ backgroundColor: '#FAFAFA' }}
            >
              {/* Stop button */}
              <div 
                className="w-5 h-5 flex items-center justify-center cursor-pointer"
                style={{ color: '#DC2626' }}
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4 13c0 .55-.45 1-1 1H9c-.55 0-1-.45-1-1V9c0-.55.45-1 1-1h6c.55 0 1 .45 1 1v6z"/>
                </svg>
              </div>
              
              {/* Timer display */}
              <span 
                className="text-[13px] font-mono tabular-nums"
                style={{ color: '#374151' }}
              >
                {formatTime(displaySeconds)}
              </span>
            </div>
          </div>
        )}

        {/* Request section - show during processing and complete states */}
        {requestText && (isProcessing || isComplete) && (
          <div className="mb-2">
            <span className="text-[10px] text-gray-500 block mb-0.5">Request:</span>
            <p 
              className="text-[11px] leading-snug"
              style={{ color: '#666666' }}
            >
              {requestText}
            </p>
          </div>
        )}

        {/* Suggestion output section */}
        {showOutput && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px]" style={{ color: '#3678E3' }}>Suggestion Output:</span>
              {/* Copy button */}
              <button className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] text-gray-500 hover:bg-gray-100 transition-colors">
                <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Copy
              </button>
            </div>
            <div 
              className="rounded p-2 text-[11px] leading-relaxed overflow-y-auto"
              style={{ 
                backgroundColor: '#FAFAFA',
                border: '1px solid rgba(54, 120, 227, 0.15)',
                color: '#1F2937',
                maxHeight: expandOutput ? 360 : 220,
              }}
            >
              {/* Render formatted output with markdown-like styling */}
              {suggestionOutput.split('\n').map((line, i) => {
                // Handle bullet points
                if (line.trim().startsWith('•') || line.trim().startsWith('-')) {
                  const content = line.trim().replace(/^[•-]\s*/, '');
                  return (
                    <div key={i} className="flex items-start gap-1.5 ml-1 my-0.5">
                      <span className="text-emerald-600 mt-0.5">•</span>
                      <span>{content}</span>
                    </div>
                  );
                }
                // Handle numbered lists
                if (/^\d+\.\s/.test(line.trim())) {
                  const match = line.trim().match(/^(\d+)\.\s(.*)$/);
                  if (match) {
                    return (
                      <div key={i} className="flex items-start gap-1.5 ml-1 my-0.5">
                        <span className="text-emerald-600 font-medium min-w-[12px]">{match[1]}.</span>
                        <span>{match[2]}</span>
                      </div>
                    );
                  }
                }
                // Handle headers (lines ending with :)
                if (line.trim().endsWith(':') && line.trim().length > 1) {
                  return (
                    <div key={i} className={`font-semibold text-gray-800 ${i > 0 ? 'mt-2' : ''}`}>
                      {line}
                    </div>
                  );
                }
                // Handle empty lines as spacing
                if (line.trim() === '') {
                  return <div key={i} className="h-2" />;
                }
                // Regular text
                return <div key={i}>{line}</div>;
              })}
            </div>

            {/* Action buttons */}
            <div className="flex items-center justify-center gap-2 mt-2">
              <button 
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-white"
                style={{ backgroundColor: 'rgba(96, 165, 250, 0.85)' }}
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                Edit
              </button>
              <button 
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-white"
                style={{ backgroundColor: 'rgba(96, 165, 250, 0.85)' }}
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refine
              </button>
            </div>
          </div>
        )}

        {/* Idle state - empty, no message inside widget */}
        {state === 'idle' && !showOutput && (
          <div className="py-2" />
        )}
      </div>
    </div>
    </>
  );
};

export default AssistantSessionWidgetMock;
