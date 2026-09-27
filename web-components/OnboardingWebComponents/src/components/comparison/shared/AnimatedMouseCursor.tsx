'use client';

import React from 'react';

interface AnimatedMouseCursorProps {
  isVisible: boolean;
  position: { x: number; y: number }; // Percentage-based (0-100)
  isDragging: boolean;
  isClicking?: boolean;
  draggedItem?: React.ReactNode;
}

/**
 * Animated mouse cursor component for drag-and-drop visualizations.
 * Renders a macOS-style arrow cursor that can carry a dragged item.
 */
const AnimatedMouseCursor: React.FC<AnimatedMouseCursorProps> = ({
  isVisible,
  position,
  isDragging,
  isClicking = false,
  draggedItem,
}) => {
  return (
    <div
      className="absolute pointer-events-none z-50"
      style={{
        left: `${position.x}%`,
        top: `${position.y}%`,
        opacity: isVisible ? 1 : 0,
        transition: 'left 1.5s cubic-bezier(0.25, 0.1, 0.25, 1), top 1.5s cubic-bezier(0.25, 0.1, 0.25, 1), opacity 0.4s ease-out',
        transform: 'translate(-2px, -2px)', // Offset so cursor tip is at position
      }}
    >
      {/* macOS-style arrow cursor */}
      <svg
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{
          filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.3))',
          transform: isClicking ? 'scale(0.9)' : 'scale(1)',
          transition: 'transform 0.1s ease-out',
        }}
      >
        {/* Black outline */}
        <path
          d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-5.07a.5.5 0 01.36-.16h6.22c.44 0 .66-.54.35-.85L6.35 3.21a.5.5 0 00-.85.35z"
          fill="black"
          stroke="black"
          strokeWidth="1"
        />
        {/* White fill */}
        <path
          d="M6.5 4.5v14.3l4-4.17a1.5 1.5 0 011.08-.48h5.1L6.5 4.5z"
          fill="white"
        />
      </svg>

      {/* Dragged item - offset below and to the right of cursor */}
      {isDragging && draggedItem && (
        <div
          className="absolute"
          style={{
            left: '12px',
            top: '16px',
            opacity: 0.9,
            filter: 'drop-shadow(0 4px 8px rgba(0,0,0,0.3))',
            transform: isClicking ? 'scale(1.05)' : 'scale(1)',
            transition: 'transform 0.15s ease-out, opacity 0.2s ease-out',
          }}
        >
          {draggedItem}
        </div>
      )}
    </div>
  );
};

export default AnimatedMouseCursor;
