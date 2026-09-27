"use client";

interface StepCounterProps {
  current: number;
  total: number;
  isComplete?: boolean;
  label?: string;
}

/**
 * StepCounter - Simple step indicator showing progress.
 * Displays "Step X of Y" with optional completion state.
 */
const StepCounter = ({
  current,
  total,
  isComplete = false,
  label,
}: StepCounterProps) => {
  return (
    <div className="flex items-center gap-2">
      {/* Step indicator */}
      <div 
        className={`text-xs font-medium px-2 py-1 rounded-full transition-colors duration-300 ${
          isComplete 
            ? 'bg-green-100 text-green-700' 
            : 'bg-gray-100 text-gray-600'
        }`}
      >
        {isComplete ? (
          <span className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            Done
          </span>
        ) : (
          `Step ${current} of ${total}`
        )}
      </div>
      
      {/* Optional label */}
      {label && (
        <span className="text-xs text-gray-500">{label}</span>
      )}
    </div>
  );
};

export default StepCounter;
