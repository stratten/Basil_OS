"use client";

import { useState } from 'react';
import AnimatedProcessingBubble, { BUBBLE_COLORS } from '../../AnimatedProcessingBubble';
import { BASIL_TEAM } from '../../../copy/teamIdentity';

interface StructuredFile {
  name: string;
  path?: string;
  isFolder?: boolean;
  isInput?: boolean; // For distinguishing input references from output files
}

interface ReferencePath {
  name: string;
  isFolder: boolean;
}

// Link item for result section (e.g., product URLs)
interface StructuredLink {
  id: string;
  label: string;
  url?: string;
}

interface AgentTaskWidgetMockProps {
  state: 'idle' | 'capture' | 'text-entry' | 'processing' | 'complete';
  /** Final transcription shown during processing (hotkey mode - not streaming) */
  transcription?: string;
  /** AgentTask text shown during processing/complete */
  agentTaskText?: string;
  /** Typed text for text-entry mode (animated typing) */
  typedText?: string;
  /** Current processing step label */
  currentStepLabel?: string;
  /** Completed steps for execution summary (in result) */
  completedSteps?: string[];
  /** Result summary shown when complete */
  resultText?: string;
  /** Files/folders created (shown as clickable links in result) */
  structuredFiles?: StructuredFile[];
  /** Links shown in result (e.g., product URLs) */
  structuredLinks?: StructuredLink[];
  /** Callback when user clicks a folder in the result */
  onFolderSelect?: (folderName: string) => void;
  /** Callback when user clicks a file in the result */
  onFileSelect?: (fileName: string) => void;
  /** Callback when user clicks a link in the result */
  onLinkClick?: (linkId: string) => void;
  /** Reference files/folders dropped onto the widget (drag-and-drop feature) */
  referencePaths?: ReferencePath[];
  /** Whether a file is currently being dragged over the widget */
  isDraggingOver?: boolean;
  /** Ref callback for the keyboard icon (for cursor animation targeting) */
  keyboardIconRef?: React.RefCallback<HTMLElement>;
  /** Ref callback for the widget container (for drag-drop cursor targeting) */
  widgetContainerRef?: React.RefCallback<HTMLDivElement>;
  className?: string;
}

/**
 * Simple markdown renderer for result text.
 * Supports: **bold**, {{link:id:label}} for inline clickable links
 */
const renderMarkdown = (
  text: string, 
  onLinkClick?: (linkId: string) => void
): React.ReactNode => {
  // Split by link pattern first: {{link:id:label}}
  const parts = text.split(/(\{\{link:[^}]+\}\})/g);
  
  return parts.map((part, partIndex) => {
    // Check if this is a link
    const linkMatch = part.match(/\{\{link:([^:]+):([^}]+)\}\}/);
    if (linkMatch && linkMatch[1] && linkMatch[2]) {
      const linkId = linkMatch[1];
      const label = linkMatch[2];
      return (
        <span
          key={partIndex}
          className="text-blue-600 underline cursor-pointer hover:text-blue-800"
          onClick={(e) => {
            e.stopPropagation();
            onLinkClick?.(linkId);
          }}
        >
          {label}
        </span>
      );
    }
    
    // Process bold markers: **text**
    const boldParts = part.split(/(\*\*[^*]+\*\*)/g);
    return boldParts.map((boldPart, boldIndex) => {
      if (boldPart.startsWith('**') && boldPart.endsWith('**')) {
        return (
          <strong key={`${partIndex}-${boldIndex}`}>
            {boldPart.slice(2, -2)}
          </strong>
        );
      }
      return <span key={`${partIndex}-${boldIndex}`}>{boldPart}</span>;
    });
  });
};

/**
 * AgentTaskWidgetMock - Faithful recreation matching the actual app.
 * 
 * Key features:
 * - Smooth transitions between all states
 * - Execution steps: collapsible section, COLLAPSED by default
 * - Result area: scrollable when content is long
 * - Wider widget width for complete state
 */
const AgentTaskWidgetMock = ({
  state,
  transcription = "",
  agentTaskText = "",
  typedText = "",
  currentStepLabel = "Processing...",
  completedSteps = [],
  resultText = "",
  structuredFiles = [],
  // structuredLinks removed - links are now inline in markdown
  onFolderSelect,
  onFileSelect,
  onLinkClick,
  referencePaths = [],
  isDraggingOver = false,
  keyboardIconRef,
  widgetContainerRef,
  className = "",
}: AgentTaskWidgetMockProps) => {
  const isCapture = state === 'capture';
  const isTextEntry = state === 'text-entry';
  const isProcessing = state === 'processing';
  const isComplete = state === 'complete';
  
  // Execution steps collapsed by default (matching app behavior)
  const [isStepsExpanded, setIsStepsExpanded] = useState(false);

  // Calculate width based on state
  const getWidth = () => {
    // Use 'auto' for mobile-friendly responsive sizing, controlled by max-width
    if (isCapture) return 160;
    if (isTextEntry) return 220; // Wider for text input
    if (isProcessing) return 280; // Slightly narrower for mobile
    if (isComplete) return 'auto'; // Let max-width control it
    return 160;
  };
  
  // Max width for responsive sizing
  const getMaxWidth = () => {
    if (isComplete) return 'min(420px, calc(100vw - 32px))'; // Responsive max
    return 'none';
  };

  // Calculate additional height for reference paths
  const hasReferences = referencePaths.length > 0;
  const referenceListHeight = hasReferences ? Math.min(referencePaths.length * 24 + 30, 90) : 0;

  // Get bubble color based on state. Sourced from BUBBLE_COLORS so the
  // processing pair stays in lockstep with the Swift source of truth via
  // the build-time generator; recording and idle pull from the same
  // constant for consistency across mocks.
  const getBubbleColors = () => {
    if (isCapture) {
      return BUBBLE_COLORS.recording;
    }
    if (isProcessing) {
      return BUBBLE_COLORS.processing;
    }
    return BUBBLE_COLORS.idle;
  };

  const bubbleColors = getBubbleColors();

  // Build box-shadow based on state
  const getBoxShadow = () => {
    if (isComplete) {
      // Complete state: subtle border glow + drop shadow
      return `
        inset 0 0 0 1px rgba(54, 120, 227, 0.3),
        0 0 0 1px rgba(54, 120, 227, 0.15),
        0 4px 6px -1px rgba(0, 0, 0, 0.1),
        0 2px 4px -1px rgba(0, 0, 0, 0.06)
      `;
    }
    // Capture/Processing state: softer outer glow
    return `
      inset 0 0 0 1px rgba(54, 120, 227, 0.3),
      0 0 0 3px rgba(54, 120, 227, 0.08),
      0 0 0 6px rgba(54, 120, 227, 0.04),
      0 4px 6px -1px rgba(0, 0, 0, 0.1)
    `;
  };

  return (
    <>
      {/* CSS for blinking cursor animation */}
      <style jsx>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    <div
        ref={widgetContainerRef}
      className={`relative rounded-2xl bg-white ${className}`}
      style={{
        width: getWidth(),
          maxWidth: getMaxWidth(),
          minWidth: isComplete ? '280px' : undefined,
          transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1), max-width 0.6s ease, box-shadow 0.3s ease',
          boxShadow: getBoxShadow(),
        overflow: 'visible', // Allow bubble to overflow
      }}
    >

      {/* Content container with smooth height transitions */}
      <div className="relative px-3 py-2">
        
        {/* ============================================ */}
        {/* CAPTURE STATE */}
        {/* ============================================ */}
        <div 
          className="transition-all duration-500 relative"
          style={{
            opacity: isCapture ? 1 : 0,
            maxHeight: isCapture ? `${300 + referenceListHeight}px` : '0px',
            overflow: 'hidden',
          }}
        >
          {isCapture && (
            <div className="flex flex-col">
              {/* Header row */}
              <div className="flex items-start justify-between pt-2">
                {/* Left side: close button + waveform icon */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className="w-3 h-3 rounded-full bg-gray-300/50 flex items-center justify-center">
                    <svg className="w-1.5 h-1.5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <svg className="w-3 h-3" style={{ color: '#3678E3' }} fill="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.15"/>
                    <path d="M12 6v12M8 9v6M16 9v6M6 11v2M18 11v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                </div>

                <div className="flex-1 text-center">
                  <span className="text-[11px] font-medium" style={{ color: '#3678E3' }}>
                    AgentTask
                  </span>
                </div>

                {/* Right side: history + keyboard icons */}
                <div className="flex flex-col items-center gap-0.5">
                  <svg className="w-2.5 h-2.5 opacity-40" style={{ color: '#3678E3' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <svg 
                    ref={keyboardIconRef as React.RefCallback<SVGSVGElement>}
                    className="w-2.5 h-2.5 opacity-40" 
                    style={{ color: '#3678E3' }} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <rect x="2" y="6" width="20" height="12" rx="2" strokeWidth={1.5} />
                    <path strokeLinecap="round" strokeWidth={1.5} d="M5 10h1M8 10h1M11 10h2M15 10h1M18 10h1M6 13h1M9 13h6M17 13h1" />
                  </svg>
                </div>
              </div>

              <div className="text-center py-2" style={{ height: '30px' }}>
                <span className="text-[9px] text-gray-400 block">Detected:</span>
                <span className="text-[10px] block" style={{ color: '#9ca3af' }}>
                  Listening...
                </span>
              </div>

              <div className="flex justify-center py-2">
                <div className="relative" style={{ overflow: 'visible' }}>
                  <AnimatedProcessingBubble 
                    size={50}
                    isProcessing={true}
                    baseColor={bubbleColors.base}
                    accentColor={bubbleColors.accent}
                  />
                </div>
              </div>

              <div className="text-center pb-2">
                <span className="text-[10px] text-gray-500">Recording...</span>
              </div>

              {/* Reference Paths List - shown when files/folders are dropped */}
              {hasReferences && (
                <div 
                  className="mt-1 pt-2 border-t border-gray-200/50"
                  style={{ 
                    maxHeight: '90px',
                    overflow: 'auto',
                    backgroundColor: 'rgba(0, 0, 0, 0.02)',
                    borderRadius: '0 0 12px 12px',
                    marginLeft: '-12px',
                    marginRight: '-12px',
                    paddingLeft: '12px',
                    paddingRight: '12px',
                    marginBottom: '-8px',
                    paddingBottom: '8px',
                  }}
                >
                  {/* Header */}
                  <div className="flex items-center gap-1 mb-1">
                    <svg className="w-2.5 h-2.5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M12.586 4.586a2 2 0 112.828 2.828l-3 3a2 2 0 01-2.828 0 1 1 0 00-1.414 1.414 4 4 0 005.656 0l3-3a4 4 0 00-5.656-5.656l-1.5 1.5a1 1 0 101.414 1.414l1.5-1.5zm-5 5a2 2 0 012.828 0 1 1 0 101.414-1.414 4 4 0 00-5.656 0l-3 3a4 4 0 105.656 5.656l1.5-1.5a1 1 0 10-1.414-1.414l-1.5 1.5a2 2 0 11-2.828-2.828l3-3z" clipRule="evenodd" />
                    </svg>
                    <span className="text-[9px] text-gray-400">References</span>
                  </div>
                  
                  {/* Reference items */}
                  <div className="space-y-0.5">
                    {referencePaths.map((ref, i) => (
                      <div key={i} className="flex items-center justify-between gap-1 group">
                        <div className="flex items-center gap-1 min-w-0 flex-1">
                          {ref.isFolder ? (
                            <svg className="w-3 h-3 text-blue-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                            </svg>
                          ) : (
                            <svg className="w-3 h-3 text-gray-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                            </svg>
                          )}
                          <span className="text-[9px] text-gray-600 truncate">{ref.name}</span>
                        </div>
                        <button className="w-3 h-3 rounded-full bg-gray-200/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                          <svg className="w-2 h-2 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Drop Zone Overlay - shown when dragging over */}
          {isCapture && isDraggingOver && (
            <div 
              className="absolute inset-0 rounded-2xl flex flex-col items-center justify-center z-10 transition-opacity duration-200"
              style={{ 
                backgroundColor: 'rgba(54, 120, 227, 0.15)',
                backdropFilter: 'blur(2px)',
              }}
            >
              <svg className="w-8 h-8 text-[#3678E3] mb-1" fill="currentColor" viewBox="0 0 20 20">
                <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
              </svg>
              <span className="text-[10px] text-[#3678E3] font-medium">Drop files here</span>
            </div>
          )}
        </div>

        {/* ============================================ */}
        {/* TEXT ENTRY STATE */}
        {/* ============================================ */}
        <div 
          className="transition-all duration-500 relative"
          style={{
            opacity: isTextEntry ? 1 : 0,
            maxHeight: isTextEntry ? '300px' : '0px',
            overflow: 'hidden',
          }}
        >
          {isTextEntry && (
            <div className="flex flex-col">
              {/* Header row - same as capture but keyboard highlighted */}
              <div className="flex items-start justify-between pt-2">
                {/* Left side: close button + waveform icon */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className="w-3 h-3 rounded-full bg-gray-300/50 flex items-center justify-center">
                    <svg className="w-1.5 h-1.5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <svg className="w-3 h-3 opacity-40" style={{ color: '#3678E3' }} fill="currentColor" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.15"/>
                    <path d="M12 6v12M8 9v6M16 9v6M6 11v2M18 11v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                </div>

                <div className="flex-1 text-center">
                  <span className="text-[11px] font-medium" style={{ color: '#3678E3' }}>
                    AgentTask
                  </span>
                </div>

                {/* Right side: history + keyboard (highlighted) icons */}
                <div className="flex flex-col items-center gap-0.5">
                  <svg className="w-2.5 h-2.5 opacity-40" style={{ color: '#3678E3' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {/* Keyboard icon - highlighted (active) */}
                  <svg className="w-2.5 h-2.5" style={{ color: '#3678E3' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <rect x="2" y="6" width="20" height="12" rx="2" strokeWidth={1.5} />
                    <path strokeLinecap="round" strokeWidth={1.5} d="M5 10h1M8 10h1M11 10h2M15 10h1M18 10h1M6 13h1M9 13h6M17 13h1" />
                  </svg>
                </div>
              </div>

              {/* "Enter AgentTask:" label */}
              <div className="mt-2 mb-1">
                <span className="text-[10px] text-gray-500">Enter AgentTask:</span>
              </div>

              {/* Text input area */}
              <div 
                className="rounded-lg border border-gray-200 bg-gray-50 p-2 min-h-[60px] mb-2"
                style={{ fontSize: '11px' }}
              >
                <span className="text-gray-800">{typedText}</span>
                {/* Blinking cursor */}
                <span 
                  className="inline-block w-0.5 h-3 bg-gray-400 ml-0.5 align-middle"
                  style={{ animation: 'blink 1s step-end infinite' }}
                />
              </div>

              {/* Send button */}
              <button 
                className="w-full py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ 
                  backgroundColor: typedText.length > 0 ? '#3678E3' : '#e5e7eb',
                  color: typedText.length > 0 ? 'white' : '#9ca3af',
                }}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                  Send
                </div>
              </button>
            </div>
          )}
        </div>

        {/* ============================================ */}
        {/* PROCESSING STATE */}
        {/* ============================================ */}
        <div 
          className="transition-all duration-500"
          style={{
            opacity: isProcessing ? 1 : 0,
            maxHeight: isProcessing ? '300px' : '0px',
            overflow: isProcessing ? 'visible' : 'hidden',
          }}
        >
          {isProcessing && (
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5">
                  <img 
                    src="/images/icons/waveform.path.png"
                    alt={BASIL_TEAM.agentTask.displayName}
                    className="w-4 h-4"
                    style={{ filter: 'invert(12%) sepia(70%) saturate(3000%) hue-rotate(210deg) brightness(70%)' }}
                  />
                  <span className="text-[13px]" style={{ color: '#3678E3' }}>
                    {BASIL_TEAM.agentTask.displayName}
                  </span>
                </div>

              <div className="relative" style={{ overflow: 'visible' }}>
                <AnimatedProcessingBubble 
                  size={36}
                  isProcessing={true}
                  baseColor={bubbleColors.base}
                  accentColor={bubbleColors.accent}
                />
              </div>
            </div>

            <div className="mb-2">
              <span className="text-[10px] text-gray-500 block mb-0.5">Request:</span>
                <p 
                  className="text-[10px] leading-snug"
                  style={{ fontWeight: 300, color: '#000000' }}
                >
                  {transcription || agentTaskText}
                </p>
                {/* Reference indicator during processing */}
                {hasReferences && (
                  <div className="flex items-center gap-1 mt-1.5">
                    <svg className="w-2.5 h-2.5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M12.586 4.586a2 2 0 112.828 2.828l-3 3a2 2 0 01-2.828 0 1 1 0 00-1.414 1.414 4 4 0 005.656 0l3-3a4 4 0 00-5.656-5.656l-1.5 1.5a1 1 0 101.414 1.414l1.5-1.5zm-5 5a2 2 0 012.828 0 1 1 0 101.414-1.414 4 4 0 00-5.656 0l-3 3a4 4 0 105.656 5.656l1.5-1.5a1 1 0 10-1.414-1.414l-1.5 1.5a2 2 0 11-2.828-2.828l3-3z" clipRule="evenodd" />
                    </svg>
                    <span className="text-[9px] text-gray-400">
                      Using: {referencePaths.map(r => r.name).join(', ')}
                    </span>
                  </div>
                )}
              </div>

              <div className="rounded py-1.5 px-2" style={{ backgroundColor: 'rgba(255, 255, 255, 0.95)' }}>
                <div className="flex items-center gap-1.5">
                  <svg
                    className="w-3.5 h-3.5 flex-shrink-0 animate-spin"
                    style={{ color: '#3678E3', animationDuration: '3s' }}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    viewBox="0 0 24 24"
                  >
                    <circle cx="12" cy="12" r="9" strokeDasharray="8 4" strokeLinecap="round" />
                  </svg>
                  
                  <span className="text-[10px] truncate" style={{ color: '#000000' }}>
                    {currentStepLabel}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ============================================ */}
        {/* COMPLETE STATE */}
        {/* ============================================ */}
        <div 
          className="transition-all duration-500"
          style={{
            opacity: isComplete ? 1 : 0,
            maxHeight: isComplete ? '600px' : '0px',
            overflow: 'visible',
          }}
        >
          {isComplete && (
            <div className="flex flex-col">
              {/* Header - outside of overflow:hidden so bubble can overflow */}
              <div className="flex items-start justify-between pt-1 pb-1" style={{ overflow: 'visible' }}>
                <div className="flex items-center gap-1.5">
                  <div className="w-5 h-5 rounded-full bg-gray-300/50 flex items-center justify-center">
                    <svg className="w-3 h-3 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div className="w-5 h-5 rounded-full bg-gray-300/50 flex items-center justify-center">
                    <svg className="w-3 h-3 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <img 
                    src="/images/icons/waveform.path.png"
                    alt=""
                    className="w-4 h-4 ml-1"
                    style={{ filter: 'brightness(0) saturate(100%) invert(14%) sepia(68%) saturate(2689%) hue-rotate(213deg) brightness(93%) contrast(107%)' }}
                  />
                  <span className="text-sm font-medium text-[#3678E3]">
                    AgentTask
                  </span>
                </div>

                <div className="relative" style={{ overflow: 'visible' }}>
                  <AnimatedProcessingBubble 
                    size={44}
                    isProcessing={false}
                    baseColor={bubbleColors.base}
                    accentColor={bubbleColors.accent}
                  />
                </div>
              </div>

              {/* Scrollable content area */}
              <div 
                className="pt-2 pb-2 space-y-3 overflow-y-auto"
                style={{ maxHeight: '380px' }}
              >
                {/* Original AgentTask */}
                <div>
                  <p className="text-xs text-gray-500 mb-0.5">AgentTask:</p>
                  <p className="text-xs text-gray-800 leading-relaxed">{agentTaskText}</p>
                </div>

                {/* Execution Steps - COLLAPSIBLE, collapsed by default */}
                {completedSteps.length > 0 && (
                  <div>
                    {/* Clickable header - matching ExecutionStepsView.swift */}
                    <div 
                      className="flex items-center justify-between px-2 py-1.5 rounded cursor-pointer hover:bg-gray-100 transition-colors"
                      style={{ backgroundColor: 'rgba(156, 163, 175, 0.1)' }}
                      onClick={() => setIsStepsExpanded(!isStepsExpanded)}
                    >
                      <div className="flex items-center gap-1.5">
                        <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                        <span className="text-[10px] text-gray-500">Execution Steps</span>
                      </div>
                      <svg 
                        className={`w-3 h-3 text-gray-400 transition-transform duration-200 ${isStepsExpanded ? 'rotate-180' : ''}`}
                        fill="none" 
                        stroke="currentColor" 
                        viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                    
                    {/* Expandable content */}
                    <div 
                      className="overflow-hidden transition-all duration-200"
                      style={{
                        maxHeight: isStepsExpanded ? '200px' : '0px',
                        opacity: isStepsExpanded ? 1 : 0,
                      }}
                    >
                      <div className="pt-2 pl-2 space-y-0.5">
                        {completedSteps.map((step, i) => (
                          <div key={i} className="flex items-start gap-1.5">
                            <svg className="w-3 h-3 text-green-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                            <span className="text-[10px] text-gray-600">{step}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* Result Box */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-gray-500">Result:</p>
                    <button className="p-1 hover:bg-gray-100 rounded transition-colors">
                      <svg className="w-3.5 h-3.5 text-[#3678E3]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                    <div className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
                      {renderMarkdown(resultText, onLinkClick)}
                    </div>
                  </div>
                </div>

                {/* Files Section */}
                {structuredFiles.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Files:</p>
                    <div className="bg-gray-50 rounded-lg p-2 border border-gray-100">
                      {structuredFiles.map((file, i) => (
                        <div 
                          key={i} 
                          className="flex items-center gap-2 hover:bg-gray-100 px-2 py-0.5 rounded cursor-pointer transition-colors"
                          onClick={() => {
                            if (file.isFolder && onFolderSelect) {
                              onFolderSelect(file.name);
                            } else if (!file.isFolder && onFileSelect) {
                              onFileSelect(file.name);
                            }
                          }}
                        >
                          {file.isFolder ? (
                            <svg className="w-4 h-4 text-blue-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                            </svg>
                          ) : (
                            <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                            </svg>
                          )}
                          <span className="text-xs text-[#3678E3] underline">{file.name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              </div>

              {/* Action Buttons - outside scroll area */}
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
                <button className="flex items-center gap-1.5 px-3 py-1.5 bg-[#3678E3]/90 text-white text-xs font-medium rounded-md hover:bg-[#3678E3] transition-colors">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <rect x="2" y="6" width="20" height="12" rx="2" strokeWidth={1.5} />
                    <path strokeLinecap="round" strokeWidth={1.5} d="M5 10h1M8 10h1M11 10h2M15 10h1M18 10h1M6 13h1M9 13h6M17 13h1" />
                  </svg>
                  Type
                </button>
                <button className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/90 text-white text-xs font-medium rounded-md hover:bg-green-600 transition-colors">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                  </svg>
                  Follow-up
                </button>
              </div>
            </div>
          )}
        </div>

        {/* IDLE STATE */}
        {state === 'idle' && (
          <div className="py-2" />
        )}
      </div>
    </div>
    </>
  );
};

export default AgentTaskWidgetMock;
