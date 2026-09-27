"use client";

import { useRef, useState, useEffect } from 'react';

/**
 * BasilWireframeWrapper - Special wireframe for the Basil AssistantSession widget.
 * Draws internal structural elements (buttons, bubble, content area) as wireframes
 * that animate in sequence then fade out as the real UI fades in.
 * 
 * Positions are calibrated to match AssistantSessionWidgetMock layout:
 * - Widget: 240px wide (320px when complete)
 * - Padding: 12px (px-3 py-3)
 * - Close/Minimize buttons: 20x20px each with 4px gap
 * - Processing bubble: 36x36px on right
 */
interface BasilWireframeWrapperProps {
  children: React.ReactNode;
  isDrawing: boolean;
  isComplete?: boolean;
  className?: string;
}

const BasilWireframeWrapper = ({ 
  children, 
  isDrawing,
  isComplete = false,
  className = "" 
}: BasilWireframeWrapperProps) => {
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
  
  // Exact positions matching AssistantSessionWidgetMock layout
  // The widget is rendered at 0.85 scale, so we work with the unscaled dimensions
  // Padding: 12px (px-3 py-3), buttons: 20x20 (w-5 h-5), gap: 4px (gap-1), bubble: 36px
  const padding = 12;
  const buttonSize = 20;
  const buttonGap = 4;
  const bubbleSize = 36;
  
  // Close button: first button at top-left
  // Position: padding + half button size for center
  const closeBtn = { 
    cx: padding + buttonSize / 2,  // 22
    cy: padding + buttonSize / 2,  // 22
    r: buttonSize / 2 - 1          // 9
  };
  
  // Minimize button: second button, after close + gap
  const minBtn = { 
    cx: padding + buttonSize + buttonGap + buttonSize / 2,  // 46
    cy: padding + buttonSize / 2,  // 22
    r: buttonSize / 2 - 1          // 9
  };
  
  // Processing bubble: positioned on far right of header row
  // The bubble uses justify-between so it's at: width - padding - bubbleSize/2
  const bubble = { 
    cx: width - padding - bubbleSize / 2,  // width - 30
    cy: padding + bubbleSize / 2,          // 30
    r: bubbleSize / 2 - 2                  // 16
  };
  
  // Title line: represents the "AssistantSession" text area
  // Starts after minimize + brain icon (~60px from left), ends before bubble
  const titleLine = { 
    x1: padding + buttonSize + buttonGap + buttonSize + buttonGap + 16 + 4,  // ~60 (after brain icon)
    y1: padding + buttonSize / 2,  // 22
    x2: width - padding - bubbleSize - 12,  // before bubble
    y2: padding + buttonSize / 2   // 22
  };
  
  // Content/output area: below the header row
  // Header takes about 44px (padding + buttons + margin)
  const headerHeight = padding + Math.max(buttonSize, bubbleSize) + 8;
  const outputBox = {
    x: padding,
    y: headerHeight,
    width: width - padding * 2,
    height: Math.max(20, height - headerHeight - padding),
    rx: 6
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
    <div ref={containerRef} className={`relative ${className}`}>
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
        @keyframes fade-in-basil {
          0%, 60% { opacity: 0; }
          100% { opacity: 1; }
        }
        .basil-outer { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-outer.animate { animation: draw-outer 0.8s ease-out forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-close { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-close.animate { animation: draw-element 0.4s ease-out 0.3s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-min { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-min.animate { animation: draw-element 0.4s ease-out 0.4s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-bubble { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-bubble.animate { animation: draw-element 0.5s ease-out 0.5s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-title { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-title.animate { animation: draw-element 0.4s ease-out 0.6s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-output { stroke-dasharray: 1; stroke-dashoffset: 1; opacity: 0; }
        .basil-output.animate { animation: draw-element 0.6s ease-out 0.8s forwards, fade-wireframe 0.5s ease-out 1.8s forwards; }
        .basil-content { opacity: 0; }
        .basil-content.animate { animation: fade-in-basil 2s ease-out forwards; }
      `}</style>
      
      {/* SVG wireframe overlay with internal elements */}
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
            className={`basil-outer ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Close button circle */}
          <circle
            cx={closeBtn.cx}
            cy={closeBtn.cy}
            r={closeBtn.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`basil-close ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Minimize button circle */}
          <circle
            cx={minBtn.cx}
            cy={minBtn.cy}
            r={minBtn.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`basil-min ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Processing bubble */}
          <circle
            cx={bubble.cx}
            cy={bubble.cy}
            r={bubble.r}
            fill="none"
            stroke={strokeColor}
            strokeWidth="1.5"
            pathLength={1}
            className={`basil-bubble ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Title line placeholder */}
          <line
            x1={titleLine.x1}
            y1={titleLine.y1}
            x2={titleLine.x2}
            y2={titleLine.y2}
            stroke={strokeColor}
            strokeWidth="1.5"
            strokeLinecap="round"
            pathLength={1}
            className={`basil-title ${isDrawing ? 'animate' : ''}`}
          />
          
          {/* Output/content area box */}
          {outputBox.height > 10 && (
            <rect
              x={outputBox.x}
              y={outputBox.y}
              width={outputBox.width}
              height={outputBox.height}
              rx={outputBox.rx}
              fill="none"
              stroke={strokeColor}
              strokeWidth="1.5"
              pathLength={1}
              className={`basil-output ${isDrawing ? 'animate' : ''}`}
            />
          )}
        </svg>
      )}
      
      {/* Content that fades in after wireframe */}
      <div className={`basil-content ${isDrawing ? 'animate' : ''}`}>
        {children}
      </div>
    </div>
  );
};

export default BasilWireframeWrapper;
