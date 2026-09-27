"use client";

import React from 'react';

interface MockTextViewerProps {
  isOpen: boolean;
  onClose: () => void;
  fileName: string;
  content: string;
}

const MockTextViewer: React.FC<MockTextViewerProps> = ({
  isOpen,
  onClose,
  fileName,
  content,
}) => {
  if (!isOpen) return null;

  return (
    <div 
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div 
        className="w-[90%] max-w-[500px] h-[80%] max-h-[400px] bg-[#2D2D2D] rounded-lg shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Title bar - macOS style */}
        <div className="h-7 bg-[#3D3D3D] flex items-center px-2 flex-shrink-0 border-b border-[#1D1D1D]">
          {/* Traffic light buttons */}
          <div className="flex items-center gap-1.5">
            <button 
              onClick={onClose}
              className="w-3 h-3 rounded-full bg-[#FF5F56] hover:bg-[#FF3B30] transition-colors flex items-center justify-center group"
            >
              <svg className="w-1.5 h-1.5 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="#4D0000" strokeWidth="2" viewBox="0 0 8 8">
                <path d="M1 1l6 6M7 1l-6 6" />
              </svg>
            </button>
            <div className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
            <div className="w-3 h-3 rounded-full bg-[#27C93F]" />
          </div>

          {/* Title */}
          <div className="flex-1 text-center">
            <span className="text-[11px] text-white/80 font-medium truncate">
              {fileName}
            </span>
          </div>

          {/* Spacer for symmetry */}
          <div className="w-14" />
        </div>

        {/* Content area - TextEdit style */}
        <div className="flex-1 overflow-auto bg-[#1E1E1E] p-3">
          <pre className="text-[10px] text-[#D4D4D4] font-mono whitespace-pre-wrap leading-relaxed">
            {content}
          </pre>
        </div>
      </div>
    </div>
  );
};

export default MockTextViewer;
