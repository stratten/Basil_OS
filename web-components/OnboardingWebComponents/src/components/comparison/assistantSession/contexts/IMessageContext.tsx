import { useState, useEffect } from 'react';
import { UseCase } from './types';

interface IMessageContextProps {
  draftReply?: string;
  showCursor?: boolean;
}

const IMessageContext = ({ draftReply, showCursor }: IMessageContextProps) => {
  const [isMobile, setIsMobile] = useState(false);
  
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Calculate dynamic height based on content and screen size
  const getHeight = () => {
    if (!draftReply) {
      return isMobile ? 320 : 280; // Taller base on mobile
    }
    
    if (isMobile) {
      // Mobile: narrower, text wraps more
      const lines = Math.ceil(draftReply.length / 28);
      return Math.min(460, 320 + (lines * 16) + 32);
    } else {
      // Desktop: wider, text wraps less
      const lines = Math.ceil(draftReply.length / 45);
      return Math.min(380, 280 + (lines * 14) + 24);
    }
  };
  
  return (
    <div 
      className="w-full bg-[#1c1c1e] rounded-lg shadow-sm border border-gray-700 overflow-hidden flex flex-col" 
      style={{ 
        height: getHeight(), 
        transition: 'height 0.6s cubic-bezier(0.4, 0, 0.2, 1)' 
      }}
    >
      {/* Window chrome */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-[#2c2c2e] border-b border-gray-700">
        <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
        <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
        <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
        <span className="ml-2 text-xs text-gray-400">Messages</span>
      </div>
      {/* Message header */}
      <div className="px-4 py-2 border-b border-gray-700 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-pink-400 to-purple-500 flex items-center justify-center text-white text-sm font-semibold">
          K
        </div>
        <div>
          <div className="text-white text-sm font-medium">Katie</div>
          <div className="text-gray-500 text-xs">iMessage</div>
        </div>
      </div>
      {/* Messages */}
      <div className="flex-1 p-3 flex flex-col gap-2 overflow-hidden">
        {/* Incoming message */}
        <div className="flex justify-start">
          <div className="bg-[#3a3a3c] text-white text-sm rounded-2xl rounded-bl-md px-3 py-2 max-w-[80%]">
            Omg Sabrina Carpenter is coming to NY!!!
          </div>
        </div>
        <div className="flex justify-start">
          <div className="bg-[#3a3a3c] text-white text-sm rounded-2xl rounded-bl-md px-3 py-2 max-w-[80%]">
            Want to go?? I&apos;m trying to get tickets
          </div>
        </div>
        {/* Timestamp */}
        <div className="text-center text-gray-500 text-xs py-1">Today 4:23 PM</div>
        {/* Reply area - shows cursor during processing, draft when pasted */}
        <div className="mt-auto">
          {draftReply ? (
            <div 
              className="bg-[#3a3a3c] rounded-2xl px-3 py-2"
              style={{ transition: 'all 0.4s ease-out' }}
            >
              <div className="text-white text-sm leading-relaxed">{draftReply}</div>
              <div className="flex justify-end mt-2">
                <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
                  <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                  </svg>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-[#3a3a3c] rounded-full px-4 py-2 flex items-center gap-2">
              {showCursor ? (
                <>
                  <span 
                    className="text-white text-sm font-light"
                    style={{
                      animation: 'cursor-blink 1s step-end infinite',
                    }}
                  >|</span>
                  <style>{`
                    @keyframes cursor-blink {
                      0%, 50% { opacity: 1; }
                      51%, 100% { opacity: 0; }
                    }
                  `}</style>
                  <span className="text-gray-500 text-sm flex-1"></span>
                </>
              ) : (
                <span className="text-gray-400 text-sm flex-1">iMessage</span>
              )}
              <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const textUseCase: UseCase = {
  id: 'text',
  label: 'Awkward Text',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  ),
  requestText: "How do I respond to a friend asking if I want to go to a Sabrina Carpenter concert that I don't really want to go to, but if she has extra tickets she's stuck with, I'd be happy to go with her?",
  outputText: `Hey! I appreciate you thinking of me! I'm not super into Sabrina honestly, but if you end up with an extra ticket and need someone to go with, I'm totally down to keep you company and have a fun night out! Otherwise no worries at all - hope you have an amazing time!`,
  duration: 16,
  contextComponent: <IMessageContext />,
};

export default IMessageContext;
