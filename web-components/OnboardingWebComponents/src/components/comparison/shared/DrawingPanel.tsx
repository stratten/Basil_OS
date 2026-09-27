"use client";

/**
 * DrawingPanel - Panel with SVG stroke-drawing animation (Stripe-style).
 * Uses pure CSS animations for smooth, jank-free rendering.
 * The border draws in, then the fill fades in, then the content appears.
 */
interface DrawingPanelProps {
  children: React.ReactNode;
  isDrawing: boolean;
  variant: 'gray' | 'green';
  className?: string;
}

const DrawingPanel = ({ children, isDrawing, variant, className = "" }: DrawingPanelProps) => {
  const radius = 12;
  const strokeWidth = 2;
  const inset = strokeWidth / 2;
  
  const width = 400;
  const height = 340;
  
  const strokeColor = variant === 'green' ? '#22c55e' : '#9ca3af';
  const fillGradient = variant === 'green' 
    ? 'url(#greenGradient)' 
    : 'url(#grayGradient)';
  
  const animId = variant === 'green' ? 'green' : 'gray';
  
  // Path starts at top-center and goes clockwise for clean closure
  const path = `
    M ${width / 2} ${inset}
    L ${width - inset - radius} ${inset}
    Q ${width - inset} ${inset} ${width - inset} ${inset + radius}
    L ${width - inset} ${height - inset - radius}
    Q ${width - inset} ${height - inset} ${width - inset - radius} ${height - inset}
    L ${inset + radius} ${height - inset}
    Q ${inset} ${height - inset} ${inset} ${height - inset - radius}
    L ${inset} ${inset + radius}
    Q ${inset} ${inset} ${inset + radius} ${inset}
    L ${width / 2} ${inset}
  `;
  
  return (
    <div className={`relative h-[380px] sm:h-[440px] ${className}`}>
      <style jsx>{`
        @keyframes draw-stroke-${animId} {
          0% { stroke-dashoffset: 1; }
          100% { stroke-dashoffset: 0; }
        }
        
        @keyframes fade-in-fill-${animId} {
          0%, 70% { opacity: 0; }
          100% { opacity: 1; }
        }
        
        @keyframes fade-in-content-${animId} {
          0%, 85% { opacity: 0; transform: translateY(8px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        
        .stroke-path-${animId} {
          stroke-dasharray: 1;
          stroke-dashoffset: 1;
        }
        
        .stroke-path-${animId}.animate {
          animation: draw-stroke-${animId} 1.5s ease-out forwards;
        }
        
        .fill-path-${animId} { opacity: 0; }
        .fill-path-${animId}.animate {
          animation: fade-in-fill-${animId} 2s ease-out forwards;
        }
        
        .content-${animId} {
          opacity: 0;
          transform: translateY(8px);
        }
        
        .content-${animId}.animate {
          animation: fade-in-content-${animId} 2s ease-out forwards;
        }
      `}</style>
      
      <svg 
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 400 340"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="greenGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#f0fdf4" />
            <stop offset="100%" stopColor="#eff6ff" />
          </linearGradient>
          <linearGradient id="grayGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#f9fafb" />
            <stop offset="100%" stopColor="#f3f4f6" />
          </linearGradient>
        </defs>
        
        {/* Fill */}
        <path
          d={path}
          fill={fillGradient}
          className={`fill-path-${animId} ${isDrawing ? 'animate' : ''}`}
        />
        
        {/* Animated stroke */}
        <path
          d={path}
          fill="none"
          stroke={strokeColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          className={`stroke-path-${animId} ${isDrawing ? 'animate' : ''}`}
        />
      </svg>
      
      <div 
        className={`absolute inset-[5px] rounded-lg overflow-hidden content-${animId} ${isDrawing ? 'animate' : ''}`}
      >
        {children}
      </div>
    </div>
  );
};

export default DrawingPanel;
