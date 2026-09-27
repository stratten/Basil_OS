"use client";

import { useState, useEffect } from 'react';

/**
 * AnimatedStepLabel - Smoothly transitions between step labels.
 * Fades out the current label, updates it, then fades back in.
 */
interface AnimatedStepLabelProps {
  steps: Array<{ time: number; label: string }>;
  currentStep: number;
  className?: string;
}

const AnimatedStepLabel = ({ steps, currentStep, className = "" }: AnimatedStepLabelProps) => {
  const [displayedStep, setDisplayedStep] = useState(currentStep);
  const [isTransitioning, setIsTransitioning] = useState(false);
  
  useEffect(() => {
    if (currentStep !== displayedStep) {
      setIsTransitioning(true);
      const timer = setTimeout(() => {
        setDisplayedStep(currentStep);
        setTimeout(() => {
          setIsTransitioning(false);
        }, 50);
      }, 400);
      return () => clearTimeout(timer);
    }
    return () => {};
  }, [currentStep, displayedStep]);
  
  const currentLabel = steps[displayedStep - 1]?.label || "Starting...";
  
  return (
    <div className={`relative h-7 overflow-hidden ${className}`}>
      <span 
        className={`text-sm text-gray-500 transition-all duration-400 ease-out inline-block ${
          isTransitioning 
            ? 'opacity-0 transform -translate-y-3' 
            : 'opacity-100 transform translate-y-0'
        }`}
      >
        {currentLabel}
      </span>
    </div>
  );
};

export default AnimatedStepLabel;
