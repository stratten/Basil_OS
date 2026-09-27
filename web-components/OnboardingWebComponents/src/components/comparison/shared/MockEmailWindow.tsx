"use client";

import { useEffect, useState } from 'react';

interface MockEmailWindowProps {
  showReply: boolean;
  replyText?: string;
  scale?: number;
  instant?: boolean; // If true, reply appears instantly (Basil paste). If false, types out (old way).
}

/**
 * MockEmailWindow - Flat, stylized email client for the workflow comparison.
 * Shows a realistic incoming email and optionally a draft reply.
 */
const MockEmailWindow = ({
  showReply,
  replyText = "",
  scale = 1,
  instant = false
}: MockEmailWindowProps) => {
  const [typedReply, setTypedReply] = useState("");
  
  // Typewriter effect for reply (only if not instant)
  useEffect(() => {
    if (!showReply || !replyText) {
      setTypedReply("");
      return;
    }
    
    if (instant) {
      // Instant paste - show all at once
      setTypedReply(replyText);
      return;
    }
    
    // Typewriter effect for old way
    setTypedReply("");
    let i = 0;
    const interval = setInterval(() => {
      if (i < replyText.length) {
        setTypedReply(prev => prev + replyText.charAt(i));
        i++;
      } else {
        clearInterval(interval);
      }
    }, 12); // Fast typing
    return () => clearInterval(interval);
  }, [showReply, replyText, instant]);

  return (
    <div
      className="relative bg-white rounded-lg shadow-lg overflow-hidden border border-gray-200"
      style={{
        width: 300,
        height: showReply ? 260 : 200,
        transform: `scale(${scale})`,
        transformOrigin: 'top left',
        transition: 'height 0.3s ease-out',
      }}
    >
      {/* Window Title Bar */}
      <div className="flex items-center justify-between bg-gray-100 border-b border-gray-200 px-3 py-1.5">
        <div className="flex items-center space-x-1">
          <span className="w-2.5 h-2.5 bg-red-500 rounded-full"></span>
          <span className="w-2.5 h-2.5 bg-yellow-500 rounded-full"></span>
          <span className="w-2.5 h-2.5 bg-green-500 rounded-full"></span>
        </div>
        <span className="text-[10px] text-gray-600 font-medium">Mail</span>
        <div className="w-8"></div>
      </div>

      {/* Email Header */}
      <div className="px-3 py-2 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-semibold text-gray-800">Re: Partnership Proposal</span>
          <span className="text-[9px] text-gray-400">2:34 PM</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center">
            <span className="text-[8px] text-white font-medium">JC</span>
          </div>
          <div>
            <p className="text-[9px] text-gray-700 font-medium">Julia Chen</p>
            <p className="text-[8px] text-gray-400">julia@meridianventures.com</p>
          </div>
        </div>
      </div>

      {/* Email Body */}
      <div className="px-3 py-2 text-[9px] text-gray-700 leading-relaxed">
        <p className="mb-1.5">Hi,</p>
        <p className="mb-1.5">
          Thanks for taking the time to meet last week. I&apos;ve been thinking about our conversation 
          and I&apos;m excited about the potential synergies between our companies.
        </p>
        <p className="mb-1.5">
          Would you be available for a follow-up call next Tuesday or Wednesday to discuss 
          the integration timeline in more detail?
        </p>
        <p>Best,<br/>Julia</p>
      </div>

      {/* Reply Draft Area */}
      {showReply && (
        <div className="absolute bottom-0 left-0 right-0 border-t border-gray-200 bg-blue-50 px-3 py-2">
          <div className="flex items-center gap-1 mb-1">
            <svg className="w-3 h-3 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
            </svg>
            <span className="text-[9px] text-blue-600 font-medium">Reply Draft</span>
          </div>
          <div className="text-[9px] text-gray-700 leading-relaxed min-h-[40px]">
            {typedReply}
            {typedReply.length < replyText.length && (
              <span className="inline-block w-px h-3 bg-blue-500 ml-0.5 animate-blink" />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default MockEmailWindow;
