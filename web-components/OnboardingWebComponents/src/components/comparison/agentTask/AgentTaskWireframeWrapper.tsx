"use client";

import { useRef, useState, useEffect } from 'react';

/**
 * AgentTaskWireframeWrapper - Wireframe specifically for AgentTaskWidgetMock.
 * 
 * Draws the CAPTURE widget layout which has:
 * - Left VStack: close button (top) + waveform icon (bottom)
 * - Center: title
 * - Right VStack: history icon (top) + keyboard icon (bottom)
 * - CENTERED bubble below the header (this is the key difference from AssistantSession)
 * 
 * The wireframe animates in, then fades out as the real widget fades in.
 */
interface AgentTaskWireframeWrapperProps {
  children: React.ReactNode;
  isDrawing: boolean;
  isComplete?: boolean;
  className?: string;
}

const AgentTaskWireframeWrapper = ({ 
  children, 
  isDrawing,
  isComplete = false,
  className = "" 
}: AgentTaskWireframeWrapperProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  
  useEffect(() => {
    if (containerRef.current) {
      const { offsetWidth, offsetHeight } = containerRef.current;
      setDimensions({ width: offsetWidth, height: offsetHeight });
    }
  }, [children, isComplete]);
  
  const { width, height } = dimensions;
  const radius = 16; // matches rounded-2xl
  
  // Layout for capture widget (160px wide)
  // Padding: 12px (px-3 py-2), buttons: 12px, icon spacing: 2px
  const padding = 12;
  const leftBtnSize = 12;   // Close button and waveform icon (w-3 = 12px)
  const rightBtnSize = 10;  // History and keyboard icons (w-2.5 = 10px)
  const iconGap = 2;        // gap-0.5 = 2px
  const bubbleSize = 50;    // Centered bubble is 50x50
  
  // Left side: close button above waveform icon
  const closeBtn = { 
    cx: padding + leftBtnSize / 2,
    cy: padding + leftBtnSize / 2 + 4,  // Adjusted up
    r: leftBtnSize / 2
  };
  
  const waveformIcon = { 
    cx: padding + leftBtnSize / 2,
    cy: padding + leftBtnSize + iconGap + leftBtnSize / 2 + 4,
    r: leftBtnSize / 2
  };
  
  // Right side: history icon above keyboard icon
  const historyIcon = { 
    cx: width - padding - rightBtnSize / 2,
    cy: padding + rightBtnSize / 2 + 4,
    r: rightBtnSize / 2
  };
  
  const keyboardIcon = { 
    cx: width - padding - rightBtnSize / 2,
    cy: padding + rightBtnSize + iconGap + rightBtnSize / 2 + 4,
    r: rightBtnSize / 2
  };
  
  // Title line: centered between left and right icons
  const titleLine = { 
    x1: padding + leftBtnSize + 8,
    y1: padding + leftBtnSize / 2 + 4,
    x2: width - padding - rightBtnSize - 8,
    y2: padding + leftBtnSize / 2 + 4
  };
  
  // CENTERED bubble - key difference from AssistantSession
  // Positioned in the middle of the widget, below the header
  // Layout: header (~34px) + detected section (~38px with padding) + py-2 (8px) + bubble center
  const headerHeight = 34;      // pt-2 + icons
  const detectedHeight = 38;    // "Detected:" section (30px height + 8px py-2)
  const bubblePadding = 8;      // py-2 above bubble
  const bubbleCenterY = headerHeight + detectedHeight + bubblePadding + bubbleSize / 2;
  
  const centeredBubble = { 
    cx: width / 2,
    cy: bubbleCenterY,
    r: bubbleSize / 2  // Full 25px radius to match the 50px bubble
  };
  
  // Outer container path
  const outerPath = width && height ? `
    M ${width / 2} 1
    L ${width - radius - 1} 1
    Q ${width - 1} 1 ${width - 1} ${radius + 1}
    L ${width - 1} ${height - radius - 1}
    Q ${width - 1} ${height - 1} ${width - radius - 1} ${height - 1}
    L ${radius + 1} ${height - 1}
    Q 1 ${height - 1} 1 ${height - radius - 1}
    L 1 ${radius + 1}
    Q 1 1 ${radius + 1} 1
    L ${width / 2} 1
  ` : '';

  const strokeColor = '#22c55e'; // green
  
  return (
    <div ref={containerRef} className={`relative ${className}`} style={{ overflow: 'visible' }}>
      <style jsx>{`
        @keyframes draw-outer {
          0% { stroke-dashoffset: 1; opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 1; }
        }
        @keyframes draw-element {
          0% { stroke-dashoffset: 1; opacity: 0; }
          10% { stroke-dashoffset: 1; opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 1; }
        }
        @keyframes fade-wireframe {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        @keyframes fade-in-content {
          0%, 60% { opacity: 0; }
          100% { opacity: 1; }
        }
        .vc-outer { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-outer.animate { animation: draw-outer 0.8s ease-out forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-close { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-close.animate { animation: draw-element 0.3s ease-out 0.2s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-waveform { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-waveform.animate { animation: draw-element 0.3s ease-out 0.3s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-history { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-history.animate { animation: draw-element 0.3s ease-out 0.4s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-keyboard { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-keyboard.animate { animation: draw-element 0.3s ease-out 0.5s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-title { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-title.animate { animation: draw-element 0.4s ease-out 0.4s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-bubble { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .vc-bubble.animate { animation: draw-element 0.6s ease-out 0.6s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .vc-content { opacity: 0; }
        .vc-content.animate { animation: fade-in-content 2s ease-out forwards; }
      `}</style>
      
      {/* SVG wireframe overlay */}
      {width > 0 && height > 0 && (
        <svg 
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox={`0 0 ${width} ${height}`}
          style={{ zIndex: 10 }}
        >
          {/* Outer container */}
          <path
            d={outerPath}
            fill="none"
            stroke={strokeColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            className={`vc-outer ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Close button (top-left) */}
          <circle
            cx={closeBtn.cx}
            cy={closeBtn.cy}
            r={closeBtn.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`vc-close ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Waveform icon (below close) */}
          <circle
            cx={waveformIcon.cx}
            cy={waveformIcon.cy}
            r={waveformIcon.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`vc-waveform ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* History icon (top-right) */}
          <circle
            cx={historyIcon.cx}
            cy={historyIcon.cy}
            r={historyIcon.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`vc-history ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Keyboard icon (below history) */}
          <circle
            cx={keyboardIcon.cx}
            cy={keyboardIcon.cy}
            r={keyboardIcon.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`vc-keyboard ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Title line (center) */}
          <line
            x1={titleLine.x1}
            y1={titleLine.y1}
            x2={titleLine.x2}
            y2={titleLine.y2}
            stroke={strokeColor}
            strokeWidth="1.5"
            strokeLinecap="round"
            pathLength={1}
            className={`vc-title ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* CENTERED bubble - the key element */}
          <circle
            cx={centeredBubble.cx}
            cy={centeredBubble.cy}
            r={centeredBubble.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="2"
            pathLength={1}
            className={`vc-bubble ${isDrawing ? 'animate' : ''}`}
          />
        </svg>
      )}
      
      {/* Content that fades in after wireframe */}
      <div className={`vc-content ${isDrawing ? 'animate' : ''}`} style={{ overflow: 'visible' }}>
        {children}
      </div>
    </div>
  );
};

export default AgentTaskWireframeWrapper;
