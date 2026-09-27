"use client";

import React from 'react';
import { ContextComponentProps } from './types';
import { MockBrowserWindow, MockAmazonProductPage, PARODY_PRODUCTS, BrowserTab } from '../../shared';

// ============================================================================
// BROWSER TABS DATA
// ============================================================================

const BROWSER_TABS: BrowserTab[] = [
  { id: 'revolve', title: 'Revolve Triple', url: 'emazon.com/dp/B00REVOLVE' },
  { id: 'mr-mean', title: 'Mr. Mean', url: 'emazon.com/dp/B00MRMEAN' },
  { id: 'oxyfresh', title: 'OxyFresh', url: 'emazon.com/dp/B00OXYFRESH' },
];

// Map tab IDs to product data
const TAB_TO_PRODUCT: Record<string, typeof PARODY_PRODUCTS[number]> = {
  'revolve': PARODY_PRODUCTS[0]!,
  'mr-mean': PARODY_PRODUCTS[1]!,
  'oxyfresh': PARODY_PRODUCTS[2]!,
};

// ============================================================================
// DESKTOP ITEMS (minimal for this demo)
// ============================================================================

interface DesktopItem {
  id: string;
  name: string;
  type: 'folder' | 'file';
  fileType?: string;
  x: number;
  y: number;
}

const DESKTOP_ITEMS: DesktopItem[] = [
  { id: 'downloads', name: 'Downloads', type: 'folder', x: 3, y: 5 },
  { id: 'notes', name: 'Shopping List.txt', type: 'file', fileType: 'txt', x: 3, y: 18 },
];

// ============================================================================
// COMPONENT
// ============================================================================

interface ProductSearchContextProps extends ContextComponentProps {
  /** Which tabs are currently visible (based on animation step) */
  visibleTabs?: string[];
  /** Currently active tab ID (controlled by AgentTaskPanel) */
  activeTab?: string;
  /** Callback when tab is clicked */
  onTabChange?: (tabId: string) => void;
}

const ProductSearchContext: React.FC<ProductSearchContextProps> = ({
  // animationStep not used here - cursor animation handled at panel level
  visibleTabs = [],
  activeTab,
  onTabChange,
}) => {
  // Browser becomes visible when first tab opens (step >= 7)
  const showBrowser = visibleTabs.length > 0;
  
  // Filter tabs to only show visible ones
  const displayTabs = BROWSER_TABS.filter(tab => visibleTabs.includes(tab.id));
  
  // Get the active tab's product, default to first visible tab
  const currentTabId = activeTab || visibleTabs[0] || 'revolve';
  const currentProduct = TAB_TO_PRODUCT[currentTabId] || PARODY_PRODUCTS[0]!
  
  return (
    <div className="relative w-full h-full min-h-[400px]">
      {/* Desktop icons layer - minimal, just for atmosphere */}
      <div className="absolute inset-0 pointer-events-none">
        {DESKTOP_ITEMS.map((item) => (
          <div
            key={item.id}
            className="absolute flex flex-col items-center gap-1"
            style={{
              left: `${item.x}%`,
              top: `${item.y}%`,
              opacity: 0.7,
            }}
          >
            {item.type === 'folder' ? (
              <img 
                src="/images/icons/folder.png" 
                alt={item.name}
                className="w-10 h-10 object-contain"
                style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}
              />
            ) : (
              <img 
                src="/images/icons/txt.png"
                alt={item.name}
                className="w-8 h-10 object-contain"
                style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}
              />
            )}
            <span 
              className="text-[10px] text-white text-center px-1 rounded max-w-[80px] truncate"
              style={{ 
                textShadow: '0 1px 2px rgba(0,0,0,0.8)',
                backgroundColor: 'rgba(0,0,0,0.3)',
              }}
            >
              {item.name}
            </span>
          </div>
        ))}
      </div>
      
      {/* Browser window - positioned on left side, responsive width */}
      <div 
        className="absolute transition-all duration-500"
        style={{
          left: '2%',
          top: '2%',
          width: '96%',
          maxWidth: '420px',
          opacity: showBrowser ? 1 : 0,
          transform: showBrowser ? 'translateY(0) scale(1)' : 'translateY(20px) scale(0.95)',
          pointerEvents: showBrowser ? 'auto' : 'none',
        }}
      >
        <MockBrowserWindow
          isVisible={showBrowser}
          tabs={displayTabs}
          {...(currentTabId && { activeTabId: currentTabId })}
          {...(onTabChange && { onTabClick: onTabChange })}
          width="100%"
          maxWidth="420px"
          contentHeight={320}
        >
          <MockAmazonProductPage product={currentProduct} />
        </MockBrowserWindow>
      </div>
    </div>
  );
};

export default ProductSearchContext;
