"use client";

import { useRef, useEffect } from 'react';

interface MockChatInterfaceProps {
  animationStep: number;
  isEmailReply?: boolean;
  showRevisionFlow?: boolean;
}

/**
 * MockChatInterface - A simplified ChatGPT-style chat interface.
 * Used inside MockBrowserWindow to show the "old way" of using AI.
 * 
 * Animation steps (with revision flow):
 * 0: Empty chat
 * 1: Pasted email content
 * 2: User typing prompt ("Write a reply...")
 * 3: AI loading/streaming
 * 4: AI response (TOO FORMAL)
 * 5: (unused)
 * 6: User asking for revision (too formal, make friendlier)
 * 7: AI loading again
 * 8: AI revised response (friendly tone)
 * 9: Selecting response to copy
 * 
 * Chat history persists - all messages remain visible and scroll down as new ones appear.
 */
const MockChatInterface = ({
  animationStep,
  isEmailReply = false,
  showRevisionFlow = false,
}: MockChatInterfaceProps) => {
  const chatContainerRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll chat container to bottom when new messages appear
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [animationStep]);

  // Email content that gets pasted
  const pastedEmailContent = isEmailReply 
    ? "Hi, Thanks for taking the time to meet last week. I've been thinking about our conversation and I'm excited about the potential synergies between our companies. Would you be available for a follow-up call next Tuesday or Wednesday? Best, Julia"
    : "The Q4 report shows strong growth across all sectors. Revenue increased by 23% YoY...";

  // The prompt the user types
  const userPrompt = isEmailReply
    ? "Write a professional reply accepting Tuesday, I'm free 10am-2pm ET"
    : "Summarize this for a board meeting";

  // FORMAL AI response (first attempt - too stiff)
  const formalResponse = `Dear Julia,

Thank you for your correspondence. I confirm my availability on Tuesday between 10:00 AM and 2:00 PM ET.

Please advise on your preferred time.

Regards,
Sam`;

  // FRIENDLY AI response (after revision)
  const friendlyResponse = `Hi Julia,

Thanks for following up! Tuesday works perfectly - I'm free 10am-2pm ET, let me know what works best.

Looking forward to it!

Best,
Sam`;

  // Revision request
  const revisionRequest = "That's too formal. Make it friendlier.";

  // Message visibility flags - messages persist once shown
  const showUserMessage1 = animationStep >= 1;
  const showTypingCursor1 = animationStep === 2;
  const showLoading1 = animationStep === 3;
  const showFormalResponse = showRevisionFlow && animationStep >= 4;
  const showRevisionRequest = showRevisionFlow && animationStep >= 6;
  const showLoading2 = showRevisionFlow && animationStep === 7;
  const showFriendlyResponse = showRevisionFlow ? animationStep >= 8 : animationStep >= 4;
  const isSelecting = animationStep >= 9 || (!showRevisionFlow && animationStep >= 5);

  // Combine content for the user message
  const fullUserMessage = animationStep >= 2
    ? `${pastedEmailContent}\n\n---\n\n${userPrompt}`
    : pastedEmailContent;

  return (
    <div
      className="flex flex-col h-full"
      style={{ backgroundColor: "#F7F7F8" }}
    >
      {/* Chat Area - scrollable */}
      <div ref={chatContainerRef} className="flex-1 p-1.5 space-y-1.5 overflow-y-auto text-[8px]">
        {/* User Message 1: Pasted content + prompt */}
        {showUserMessage1 && (
          <div className="flex justify-end">
            <div
              className="max-w-[88%] px-1.5 py-1 rounded-lg leading-tight"
              style={{
                backgroundColor: "#FFFFFF",
                border: "1px solid #E5E7EB",
                color: "#1F2937",
              }}
            >
              <div className="whitespace-pre-wrap line-clamp-4">
                {fullUserMessage}
              </div>
              {showTypingCursor1 && (
                <span className="inline-block w-px h-2 bg-gray-800 ml-0.5 animate-blink" />
              )}
            </div>
          </div>
        )}

        {/* Loading 1 */}
        {showLoading1 && (
          <div className="flex justify-start">
            <div className="px-1.5 py-1 rounded-lg flex gap-0.5" style={{ backgroundColor: "#F3F4F6" }}>
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}

        {/* AI Response 1: Formal (stays visible) */}
        {showFormalResponse && !showLoading1 && (
          <div className="flex justify-start">
            <div
              className="max-w-[88%] px-1.5 py-1 rounded-lg leading-tight"
              style={{ backgroundColor: "#F3F4F6", color: "#1F2937" }}
            >
              <div className="whitespace-pre-wrap line-clamp-5">
                {formalResponse}
              </div>
            </div>
          </div>
        )}

        {/* User Message 2: Revision request (stays visible) */}
        {showRevisionRequest && !showLoading1 && (
          <div className="flex justify-end">
            <div
              className="max-w-[85%] px-1.5 py-1 rounded-lg leading-tight"
              style={{
                backgroundColor: "#FFFFFF",
                border: "1px solid #E5E7EB",
                color: "#DC2626",
              }}
            >
              {revisionRequest}
            </div>
          </div>
        )}

        {/* Loading 2 */}
        {showLoading2 && (
          <div className="flex justify-start">
            <div className="px-1.5 py-1 rounded-lg flex gap-0.5" style={{ backgroundColor: "#F3F4F6" }}>
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
              <div className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}

        {/* AI Response 2: Friendly (or only response if no revision flow) */}
        {showFriendlyResponse && !showLoading1 && !showLoading2 && (
          <div className="flex justify-start">
            <div
              className={`max-w-[88%] px-1.5 py-1 rounded-lg leading-tight ${isSelecting ? 'ring-2 ring-blue-400' : ''}`}
              style={{
                backgroundColor: isSelecting ? "#DBEAFE" : "#F3F4F6",
                color: "#1F2937",
              }}
            >
              <div className="whitespace-pre-wrap line-clamp-5">
                {friendlyResponse}
              </div>
            </div>
          </div>
        )}

      </div>

      {/* Input Area */}
      <div className="p-1 border-t" style={{ borderColor: "#E5E7EB", backgroundColor: "#FFFFFF" }}>
        <div
          className="flex items-center gap-1 px-1 py-0.5 rounded-md"
          style={{ backgroundColor: "#F9FAFB", border: "1px solid #E5E7EB" }}
        >
          <span className="text-[6px] text-gray-400 flex-1">Message ChatGPT...</span>
          <div className="w-3 h-3 rounded-full flex items-center justify-center" style={{ backgroundColor: "#E5E7EB" }}>
            <svg className="w-1.5 h-1.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MockChatInterface;
