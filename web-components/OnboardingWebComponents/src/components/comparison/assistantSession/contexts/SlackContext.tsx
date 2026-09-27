import { useState, useEffect } from 'react';
import { UseCase } from './types';

interface SlackContextProps {
  draftReply?: string;
  showCursor?: boolean;
}

const SlackContext = ({ draftReply, showCursor }: SlackContextProps) => {
  const [isMobile, setIsMobile] = useState(false);
  
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Calculate dynamic height based on content and screen size
  const getHeight = () => {
    const baseHeight = isMobile ? 380 : 340;
    if (!draftReply) return baseHeight;
    const charsPerLine = isMobile ? 25 : 30;
    const lines = Math.ceil(draftReply.length / charsPerLine);
    return Math.min(isMobile ? 520 : 480, baseHeight + (lines * 16));
  };
  
  // Messages area height - taller on mobile where text wraps more
  const messagesHeight = isMobile ? 115 : 95;

  return (
    <div 
      className="w-full bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col" 
      style={{ 
        height: getHeight(),
        transition: 'height 0.6s cubic-bezier(0.4, 0, 0.2, 1)'
      }}
    >
      {/* Window chrome */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-[#4A154B] border-b border-[#3d1140]">
        <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
        <div className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
        <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
        <span className="ml-2 text-xs text-white/80">Slack</span>
      </div>
      {/* Channel header */}
      <div className="px-4 py-2 border-b border-gray-200 flex items-center gap-2">
        {/* Star icon */}
        <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
        </svg>
        <span className="text-sm font-semibold text-gray-900"># engineering</span>
        <div className="ml-auto flex items-center gap-1.5">
          {/* Member count button */}
          <div className="flex items-center gap-1 px-1.5 py-0.5 border border-gray-300 rounded">
            <svg className="w-3.5 h-3.5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
            <span className="text-xs text-gray-600">12</span>
          </div>
          {/* Huddle/call button - headphones icon */}
          <div className="p-1 border border-gray-300 rounded">
            <svg className="w-3.5 h-3.5 text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3a7 7 0 00-7 7v4a4 4 0 004 4h1v-6H7v-2a5 5 0 0110 0v2h-3v6h1a4 4 0 004-4v-4a7 7 0 00-7-7z" />
            </svg>
          </div>
          {/* Search */}
          <div className="p-1 border border-gray-300 rounded">
            <svg className="w-3.5 h-3.5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          {/* More options - no border */}
          <svg className="w-4 h-4 text-gray-500" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" />
          </svg>
        </div>
      </div>
      {/* Tabs */}
      <div className="px-4 py-1 border-b border-gray-200 flex items-center gap-4 text-xs">
        <span className="text-gray-900 font-medium border-b-2 border-gray-900 pb-1">Messages</span>
        <span className="text-gray-500">Files</span>
        <span className="text-gray-500">Pins</span>
        <span className="text-gray-400">+</span>
      </div>
      {/* Messages - fixed height so input expands downward, not this area */}
      <div className="p-3 pb-4 flex flex-col gap-2 bg-white" style={{ height: messagesHeight }}>
        {/* Message from coworker */}
        <div className="flex gap-2">
          <span className="text-[10px] text-gray-400 pt-1 w-10 text-right flex-shrink-0">2:47 PM</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm font-bold text-gray-900">Marcus Lee</span>
            </div>
            <div className="text-sm text-gray-700 mt-0.5 leading-relaxed">
              Quick q - what&apos;s the difference between <code className="px-1 py-0.5 bg-[#f8f8f8] border border-gray-200 rounded text-xs font-mono text-[#e01e5a]">useMemo</code> and <code className="px-1 py-0.5 bg-[#f8f8f8] border border-gray-200 rounded text-xs font-mono text-[#e01e5a]">useCallback</code> again? I always mix them up 😅
            </div>
          </div>
        </div>
      </div>
      {/* Message input - expands to fill remaining space */}
      <div className="flex-1 min-h-0 px-3 pb-3 flex flex-col">
        <div className="rounded-lg border border-gray-300 overflow-hidden flex-1 min-h-0 flex flex-col">
          {/* Formatting toolbar */}
          <div className="flex items-center gap-0.5 px-2 py-1 bg-gray-50 border-b border-gray-200">
            {/* Bold */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-600">
              <span className="text-xs font-bold">B</span>
            </button>
            {/* Italic */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-600">
              <span className="text-xs italic font-serif">I</span>
            </button>
            {/* Underline */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-600">
              <span className="text-xs underline">U</span>
            </button>
            {/* Strikethrough */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-600">
              <span className="text-xs line-through">S</span>
            </button>
            <div className="w-px h-4 bg-gray-300 mx-1" />
            {/* Link */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
            {/* Numbered list */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                <text x="2" y="7" fontSize="6" fontFamily="sans-serif">1</text>
                <rect x="8" y="4" width="14" height="2" rx="1" />
                <text x="2" y="14" fontSize="6" fontFamily="sans-serif">2</text>
                <rect x="8" y="11" width="14" height="2" rx="1" />
                <text x="2" y="21" fontSize="6" fontFamily="sans-serif">3</text>
                <rect x="8" y="18" width="14" height="2" rx="1" />
              </svg>
            </button>
            {/* Bulleted list */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <circle cx="4" cy="5" r="2" />
                <rect x="8" y="4" width="14" height="2" rx="1" />
                <circle cx="4" cy="12" r="2" />
                <rect x="8" y="11" width="14" height="2" rx="1" />
                <circle cx="4" cy="19" r="2" />
                <rect x="8" y="18" width="14" height="2" rx="1" />
              </svg>
            </button>
            <div className="w-px h-4 bg-gray-300 mx-1" />
            {/* Blockquote */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <rect x="2" y="4" width="3" height="16" rx="1" />
                <rect x="8" y="6" width="14" height="2" rx="1" />
                <rect x="8" y="11" width="10" height="2" rx="1" />
                <rect x="8" y="16" width="12" height="2" rx="1" />
              </svg>
            </button>
            {/* Inline Code */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </button>
            {/* Code Block - rectangle with </> in corner */}
            <button className="p-1 rounded hover:bg-gray-200 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {/* Rectangle outline with gap in top-left */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4h7a1 1 0 011 1v14a1 1 0 01-1 1H5a1 1 0 01-1-1V12" />
                {/* < bracket */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 2L1 5l3 3" />
                {/* / slash */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 8L8 2" />
                {/* > bracket */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 2l3 3-3 3" />
              </svg>
            </button>
          </div>
          {/* Input area - flex-1 to fill remaining space, min-h-0 allows scrolling */}
          {draftReply ? (
            <div 
              className="flex-1 min-h-0 bg-white px-3 py-2 text-sm text-gray-800 leading-relaxed overflow-y-auto whitespace-pre-wrap"
              style={{ transition: 'all 0.4s ease-out' }}
            >
              {draftReply}
            </div>
          ) : (
            <div className="flex-1 bg-white px-3 py-2 flex items-start gap-2">
              {showCursor ? (
                <>
                  <span 
                    className="text-gray-800 text-sm font-light"
                    style={{ animation: 'cursor-blink 1s step-end infinite' }}
                  >|</span>
                  <style>{`
                    @keyframes cursor-blink {
                      0%, 50% { opacity: 1; }
                      51%, 100% { opacity: 0; }
                    }
                  `}</style>
                </>
              ) : (
                <span className="text-sm text-gray-400">Message #engineering</span>
              )}
              <div className="ml-auto flex items-center gap-1.5">
                <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const slackUseCase: UseCase = {
  id: 'slack',
  label: 'Slack Reply',
  icon: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
    </svg>
  ),
  requestText: "Explain the difference concisely - useMemo caches values, useCallback caches functions",
  outputText: `Both are for performance optimization, but they cache different things:

useMemo:
• Caches a computed value
• Use when you have an expensive calculation you don't want to re-run every render

useCallback:
• Caches a function reference
• Use when passing callbacks to child components that rely on reference equality

Quick rule: returning a value? useMemo. Returning a function? useCallback. (useCallback is actually just useMemo(() => fn, deps) under the hood)`,
  duration: 20,
  contextComponent: <SlackContext />,
};

export default SlackContext;
