"use client";

import { ReactNode } from 'react';

export interface BrowserTab {
  id: string;
  title: string;
  url: string;
  favicon?: ReactNode;
}

interface MockBrowserWindowProps {
  isVisible: boolean;
  children: ReactNode;
  scale?: number;
  className?: string;
  /** Browser tabs - if provided, renders tab bar */
  tabs?: BrowserTab[];
  /** Currently active tab ID */
  activeTabId?: string;
  /** Callback when tab is clicked */
  onTabClick?: (tabId: string) => void;
  /** URL to display (used when no tabs provided) */
  url?: string;
  /** Custom width - number (px) or string (e.g., '100%') */
  width?: number | string;
  /** Max width for responsive sizing */
  maxWidth?: string;
  /** Custom content height */
  contentHeight?: number;
}

/**
 * MockBrowserWindow - A stylized browser window with optional tabs and URL bar.
 * Supports single-page mode (children only) or multi-tab mode with tab switching.
 */
const MockBrowserWindow = ({
  isVisible,
  children,
  scale = 1,
  className = "",
  tabs,
  activeTabId,
  onTabClick,
  url = "chatgpt.com",
  width = 320,
  maxWidth,
  contentHeight = 280,
}: MockBrowserWindowProps) => {
  if (!isVisible) return null;

  const activeTab = tabs?.find(t => t.id === activeTabId) || tabs?.[0];
  const displayUrl = activeTab?.url || url;
  const hasTabs = tabs && tabs.length > 0;

  return (
    <div
      className={`bg-white rounded-lg overflow-hidden transition-all duration-300 ${className}`}
      style={{
        transform: `scale(${scale})`,
        transformOrigin: "top left",
        boxShadow: "0 4px 6px rgba(0,0,0,0.1), 0 10px 15px rgba(0,0,0,0.1)",
        border: "1px solid #E5E7EB",
        width,
        maxWidth: maxWidth || undefined,
        opacity: isVisible ? 1 : 0,
      }}
    >
      {/* Browser Chrome - Title Bar with Traffic Lights and Tabs */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ backgroundColor: "#F9FAFB", borderBottom: hasTabs ? "none" : "1px solid #E5E7EB" }}
      >
        {/* Traffic light buttons */}
        <div className="flex gap-1.5 flex-shrink-0">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#FF5F57" }} />
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#FEBC2E" }} />
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: "#28C840" }} />
        </div>

        {/* Tabs (inline with traffic lights) */}
        {hasTabs && (
          <div className="flex items-center gap-0.5 flex-1 min-w-0 ml-2">
            {tabs.map((tab, index) => {
              const isActive = tab.id === (activeTabId || tabs[0]?.id);
              return (
                <button
                  key={tab.id}
                  onClick={() => onTabClick?.(tab.id)}
                  className={`px-2 py-1 text-[10px] rounded transition-all duration-200 flex items-center gap-1 max-w-[90px] ${
                    isActive 
                      ? 'bg-white text-gray-800 shadow-sm' 
                      : 'bg-gray-200/60 text-gray-500 hover:bg-gray-200'
                  }`}
                  style={{ zIndex: isActive ? 10 : index }}
                >
                  {tab.favicon && <span className="w-2.5 h-2.5 flex-shrink-0">{tab.favicon}</span>}
                  <span className="truncate">{tab.title}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* URL Bar (when no tabs) */}
        {!hasTabs && (
          <>
            <div
              className="flex-1 flex items-center gap-2 px-2 py-1 rounded"
              style={{ backgroundColor: "#FFFFFF", border: "1px solid #E5E7EB" }}
            >
              <svg className="w-3 h-3 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              <span className="text-xs text-gray-600 truncate">{displayUrl}</span>
            </div>
            <div className="flex gap-0.5">
              <div className="w-1 h-1 rounded-full bg-gray-400" />
              <div className="w-1 h-1 rounded-full bg-gray-400" />
              <div className="w-1 h-1 rounded-full bg-gray-400" />
            </div>
          </>
        )}
      </div>

      {/* URL Bar (when tabs provided - below tabs) */}
      {hasTabs && (
        <div
          className="flex items-center gap-2 px-3 py-1.5 bg-white"
          style={{ borderBottom: "1px solid #E5E7EB" }}
        >
          <div
            className="flex-1 flex items-center gap-2 px-2 py-1 rounded"
            style={{ backgroundColor: "#F9FAFB", border: "1px solid #E5E7EB" }}
          >
            <svg className="w-3 h-3 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            <span className="text-xs text-gray-600 truncate">{displayUrl}</span>
          </div>
          <div className="flex gap-0.5">
            <div className="w-1 h-1 rounded-full bg-gray-400" />
            <div className="w-1 h-1 rounded-full bg-gray-400" />
            <div className="w-1 h-1 rounded-full bg-gray-400" />
          </div>
        </div>
      )}

      {/* Browser Content Area */}
      <div style={{ height: contentHeight }} className="overflow-hidden">
        {children}
      </div>
    </div>
  );
};

export default MockBrowserWindow;
