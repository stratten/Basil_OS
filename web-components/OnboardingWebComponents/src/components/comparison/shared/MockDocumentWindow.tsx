"use client";

interface MockDocumentWindowProps {
  title?: string;
  highlightedText?: boolean;
  cursorPosition?: 'start' | 'middle' | 'end';
  insertedText?: string | undefined;
  scale?: number;
  className?: string;
}

/**
 * MockDocumentWindow - A flat, stylized document mockup (Stripe-style).
 * Shows a macOS-style window with simulated text content.
 */
const MockDocumentWindow = ({
  title = "quarterly_report.docx",
  highlightedText = false,
  cursorPosition,
  insertedText,
  scale = 1,
  className = "",
}: MockDocumentWindowProps) => {
  // Simulated text lines with varying widths
  const textLines = [
    { width: "90%", isHighlightable: false },
    { width: "85%", isHighlightable: false },
    { width: "75%", isHighlightable: true },  // This line gets highlighted
    { width: "80%", isHighlightable: true },  // This line gets highlighted
    { width: "60%", isHighlightable: true },  // This line gets highlighted
    { width: "70%", isHighlightable: false },
    { width: "88%", isHighlightable: false },
    { width: "45%", isHighlightable: false },
  ];

  return (
    <div
      className={`bg-white rounded-lg overflow-hidden ${className}`}
      style={{
        transform: `scale(${scale})`,
        transformOrigin: "top left",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1), 0 4px 6px rgba(0,0,0,0.05)",
        border: "1px solid #E5E7EB",
        width: 280,
      }}
    >
      {/* Window Chrome - Title Bar */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ backgroundColor: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}
      >
        {/* Traffic light buttons */}
        <div className="flex gap-1.5">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#FF5F57" }} />
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#FEBC2E" }} />
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#28C840" }} />
        </div>
        
        {/* Document title */}
        <div className="flex-1 text-center">
          <span className="text-xs text-gray-500 font-medium">{title}</span>
        </div>
        
        {/* Spacer for symmetry */}
        <div className="w-12" />
      </div>

      {/* Document Content Area */}
      <div className="p-4 space-y-2" style={{ minHeight: 160 }}>
        {/* Document title line */}
        <div
          className="h-3 rounded mb-4"
          style={{ width: "50%", backgroundColor: "#1F2937" }}
        />
        
        {/* Text lines */}
        {textLines.map((line, index) => {
          const isThisLineHighlighted = highlightedText && line.isHighlightable;
          
          return (
            <div key={index} className="relative">
              {/* Selection background */}
              {isThisLineHighlighted && (
                <div
                  className="absolute inset-0 rounded-sm"
                  style={{
                    backgroundColor: "#DBEAFE",
                    marginLeft: -2,
                    marginRight: -2,
                    paddingLeft: 2,
                    paddingRight: 2,
                  }}
                />
              )}
              
              {/* Text line */}
              <div
                className="h-2 rounded relative"
                style={{
                  width: line.width,
                  backgroundColor: isThisLineHighlighted ? "#3B82F6" : "#D1D5DB",
                }}
              />
            </div>
          );
        })}

        {/* Inserted text indicator */}
        {insertedText && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div
              className="h-2 rounded mb-1"
              style={{ width: "70%", backgroundColor: "#10B981" }}
            />
            <div
              className="h-2 rounded mb-1"
              style={{ width: "85%", backgroundColor: "#10B981" }}
            />
            <div
              className="h-2 rounded"
              style={{ width: "55%", backgroundColor: "#10B981" }}
            />
          </div>
        )}

        {/* Cursor indicator */}
        {cursorPosition && (
          <div
            className="absolute w-0.5 h-4 bg-blue-500 animate-pulse"
            style={{
              left: cursorPosition === 'start' ? '16px' : 
                    cursorPosition === 'middle' ? '50%' : 'calc(100% - 16px)',
            }}
          />
        )}
      </div>
    </div>
  );
};

export default MockDocumentWindow;
