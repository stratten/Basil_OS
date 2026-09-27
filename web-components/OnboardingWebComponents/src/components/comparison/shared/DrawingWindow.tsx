"use client";

import { useRef, useState, useEffect } from 'react';

/**
 * DrawingWindow - Wraps child content with an SVG wireframe that draws in
 * and then fades out as the content fades in.
 * Uses refs to measure actual child dimensions for accurate wireframe sizing.
 */
interface DrawingWindowProps {
  children: React.ReactNode;
  isDrawing: boolean;
  delay?: number;
  variant?: 'blue' | 'gray' | 'green';
  className?: string;
}

const DrawingWindow = ({ 
  children, 
  isDrawing, 
  delay = 0,
  variant = 'gray',
  className = "" 
}: DrawingWindowProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const hasMeasuredRef = useRef(false);
  
  // Only measure once when isDrawing first becomes true
  // Don't re-measure when children change (e.g., when draftReply is added)
  useEffect(() => {
    if (!isDrawing) {
      // Reset measurement flag when animation resets
      hasMeasuredRef.current = false;
      setDimensions({ width: 0, height: 0 });
      return;
    }
    
    if (hasMeasuredRef.current) return; // Already measured for this animation cycle
    
    // Small delay to ensure children have rendered and have dimensions
    const timer = setTimeout(() => {
      if (containerRef.current && !hasMeasuredRef.current) {
        const { offsetWidth, offsetHeight } = containerRef.current;
        setDimensions({ width: offsetWidth, height: offsetHeight });
        hasMeasuredRef.current = true;
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [isDrawing]);
  
  const radius = 8;
  const { width, height } = dimensions;
  
  const strokeColor = variant === 'blue' ? '#3b82f6' : variant === 'green' ? '#22c55e' : '#9ca3af';
  const delayMs = Math.round(delay * 1000);
  const animId = `window-${variant}-${delayMs}`;
  
  // Path starts at top-center and goes clockwise for clean closure
  const path = width && height ? `
    M ${width / 2} 0
    L ${width - radius} 0
    Q ${width} 0 ${width} ${radius}
    L ${width} ${height - radius}
    Q ${width} ${height} ${width - radius} ${height}
    L ${radius} ${height}
    Q 0 ${height} 0 ${height - radius}
    L 0 ${radius}
    Q 0 0 ${radius} 0
    L ${width / 2} 0
  ` : '';
  
  return (
    <div ref={containerRef} className={`relative h-full ${className}`}>
      <style jsx>{`
        @keyframes draw-stroke-${animId} {
          0% { stroke-dashoffset: 1; }
          100% { stroke-dashoffset: 0; }
        }
        @keyframes fade-out-stroke-${animId} {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        @keyframes fade-in-content-${animId} {
          0% { opacity: 0; }
          100% { opacity: 1; }
        }
        .wireframe-stroke-${animId} {
          stroke-dasharray: 1;
          stroke-dashoffset: 1;
          opacity: 1;
        }
        .wireframe-stroke-${animId}.animate {
          animation: 
            draw-stroke-${animId} 1s ease-out ${delay}s forwards,
            fade-out-stroke-${animId} 0.5s ease-out ${delay + 1.2}s forwards;
        }
        .wireframe-content-${animId} {
          opacity: 0;
        }
        .wireframe-content-${animId}.animate {
          animation: fade-in-content-${animId} 0.6s ease-out ${delay + 1}s forwards;
        }
      `}</style>
      
      {/* SVG wireframe overlay */}
      {width > 0 && height > 0 && isDrawing && (
        <svg 
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox={`0 0 ${width} ${height}`}
          style={{ zIndex: 10 }}
        >
          <path
            d={path}
            fill="none"
            stroke={strokeColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            className={`wireframe-stroke-${animId} animate`}
          />
        </svg>
      )}
      
      {/* Content that fades in */}
      <div className={`h-full wireframe-content-${animId} ${isDrawing ? 'animate' : ''}`}>
        {children}
      </div>
    </div>
  );
};

export default DrawingWindow;
