import React from 'react';

export interface AgentTaskStep {
  label: string;
}

export type AgentTaskPhase = 'idle' | 'capture' | 'processing' | 'complete';

// Props for context components that support navigation
export interface ContextComponentProps {
  animationStep: number;
  navigationPath?: string[];
  onNavigate?: (path: string[]) => void;
  onFileOpen?: (fileName: string) => void;
  /** Controlled file viewing - when set, shows the file viewer for this file */
  viewingFile?: string | null;
  /** Callback when file viewer is closed */
  onCloseFile?: () => void;
  /** Which tabs are currently visible (for browser-based demos) */
  visibleTabs?: string[];
  /** Currently active tab ID */
  activeTab?: string;
  /** Callback when tab is clicked */
  onTabChange?: (tabId: string) => void;
}

// Reference path for drag-and-drop feature
export interface ReferencePath {
  name: string;
  isFolder: boolean;
}

// Structured file/folder shown in result
export interface StructuredFile {
  name: string;
  path?: string;
  isFolder?: boolean;
  isInput?: boolean; // For distinguishing input references from output files
}

// Structured link shown in result (e.g., product URLs)
export interface StructuredLink {
  id: string;
  label: string;
  url?: string;
}

export interface AgentTaskUseCase {
  id: string;
  label: string;
  icon: React.ReactNode;
  
  // Timing
  duration: number;
  getPhase: (time: number) => AgentTaskPhase;
  
  // Capture phase
  getTranscript: (time: number) => string;
  getCaptureProgress: (time: number) => number; // 0-1 for ring
  
  // Processing phase  
  getStep: (time: number) => { index: number; label: string };
  totalSteps: number;
  steps: AgentTaskStep[];
  
  // Complete phase
  commandText: string;
  resultSummary: string;
  completedSteps?: string[];  // Steps shown in result execution summary
  structuredFiles?: StructuredFile[];  // Files/folders created
  structuredLinks?: StructuredLink[];  // Links shown in result (e.g., product URLs)
  
  // Drag-and-drop reference feature (optional)
  getReferencePaths?: (time: number) => ReferencePath[];
  isDraggingOver?: (time: number) => boolean;
  
  // Text entry mode (optional) - uses keyboard input instead of voice
  isTextEntryMode?: boolean;
  getTypedText?: (time: number) => string;
  getIsTextEntryActive?: (time: number) => boolean; // Returns true when showing text entry UI
  
  // Browser tabs feature (optional) - for web research demos
  getVisibleTabs?: (time: number) => string[];
  
  // Context rendering - updated to support navigation props
  ContextComponent: React.ComponentType<ContextComponentProps>;
  getAnimationStep: (time: number) => number;
}
