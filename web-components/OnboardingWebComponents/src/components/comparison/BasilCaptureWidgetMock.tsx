"use client";

import AnimatedProcessingBubble, { BUBBLE_COLORS } from '../AnimatedProcessingBubble';

interface BasilCaptureWidgetMockProps {
  state: 'idle' | 'listening' | 'processing' | 'complete';
  detectedWords?: string[];
  statusMessage?: string;
  className?: string;
}

/**
 * BasilCaptureWidgetMock - Faithful reconstruction of the AgentTaskCaptureWidget.
 * Matches the actual app's design: white bg, blue border, shadow strokes, header, bubble.
 * Size: 160x188px (matches actual app).
 */
const BasilCaptureWidgetMock = ({
  state,
  detectedWords = [],
  statusMessage,
  className = "",
}: BasilCaptureWidgetMockProps) => {
  const isListening = state === 'listening';
  const isProcessing = state === 'processing';
  const isComplete = state === 'complete';

  // Determine status message based on state
  const displayStatus = statusMessage || (
    state === 'idle' ? 'Ready' :
    state === 'listening' ? 'Listening...' :
    state === 'processing' ? 'Processing...' :
    'Complete'
  );

  // Detected words display (last 3 words)
  const displayWords = detectedWords.length > 0 
    ? detectedWords.slice(-3).join(' ') 
    : 'Listening...';

  return (
    <div
      className={`relative rounded-2xl bg-white overflow-hidden ${className}`}
      style={{
        width: 160,
        height: 188,
      }}
    >
      {/* Border layers - matching app aesthetic */}
      <div 
        className="absolute inset-0 rounded-2xl pointer-events-none"
        style={{
          border: '1px solid rgba(54, 120, 227, 0.3)',
        }}
      />
      <div 
        className="absolute rounded-[19px] pointer-events-none"
        style={{
          inset: '-3px',
          border: '3px solid rgba(0, 0, 0, 0.1)',
        }}
      />
      <div 
        className="absolute rounded-[21px] pointer-events-none"
        style={{
          inset: '-5px',
          border: '5px solid rgba(0, 0, 0, 0.05)',
        }}
      />

      {/* Content */}
      <div className="relative h-full flex flex-col px-3 py-2">
        {/* Header row */}
        <div className="flex items-center justify-between mb-2">
          {/* Left side: close button + waveform icon */}
          <div className="flex flex-col items-center gap-1">
            {/* Close button */}
            <div 
              className="w-4 h-4 rounded-full flex items-center justify-center"
              style={{ backgroundColor: 'rgba(54, 120, 227, 0.1)' }}
            >
              <svg className="w-2.5 h-2.5" style={{ color: '#6B7280' }} fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </div>
            
            {/* Waveform icon */}
            <svg 
              className="w-4 h-4" 
              style={{ color: '#3678E3' }} 
              fill="currentColor" 
              viewBox="0 0 24 24"
            >
              <path d="M12 3v18m-4-14v10m-4-6v2m16-6v10m-4-14v18" 
                    stroke="currentColor" 
                    strokeWidth="2" 
                    strokeLinecap="round"
                    fill="none" />
            </svg>
          </div>

          {/* Title */}
          <span 
            className="text-[11px] font-medium"
            style={{ color: '#3678E3' }}
          >
            Voice AgentTask
          </span>

          {/* Right side: secondary icons */}
          <div className="flex flex-col items-center gap-1">
            <svg className="w-3 h-3 opacity-40" style={{ color: '#3678E3' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <svg className="w-3 h-3 opacity-40" style={{ color: '#3678E3' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
        </div>

        {/* Detected words section */}
        <div className="text-center mb-2">
          <span className="text-[9px] text-gray-500 block mb-0.5">Detected:</span>
          <span 
            className="text-[10px]"
            style={{ color: detectedWords.length > 0 ? '#3678E3' : '#9CA3AF' }}
          >
            {displayWords}
          </span>
        </div>

        {/* Animated bubble */}
        <div className="flex-1 flex items-center justify-center">
          {/* Bubble colours come from BUBBLE_COLORS so the processing pair
              stays in lockstep with the Swift source of truth via the
              build-time generator. */}
          <div className="relative">
            <AnimatedProcessingBubble
              size={50}
              isProcessing={isListening || isProcessing}
              baseColor={(isListening
                ? BUBBLE_COLORS.recording
                : isProcessing
                  ? BUBBLE_COLORS.processing
                  : BUBBLE_COLORS.idle).base}
              accentColor={(isListening
                ? BUBBLE_COLORS.recording
                : isProcessing
                  ? BUBBLE_COLORS.processing
                  : BUBBLE_COLORS.idle).accent}
            />
            
            {/* Complete checkmark overlay */}
            {isComplete && (
              <div 
                className="absolute inset-0 flex items-center justify-center rounded-full"
                style={{ backgroundColor: 'rgba(52, 135, 56, 0.9)' }}
              >
                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
              </div>
            )}
          </div>
        </div>

        {/* Status text */}
        <div className="text-center mt-auto pb-1">
          <span className="text-[10px] text-gray-500">{displayStatus}</span>
        </div>
      </div>
    </div>
  );
};

export default BasilCaptureWidgetMock;
