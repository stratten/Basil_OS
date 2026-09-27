"use client";

import { useState, useEffect, useRef, useCallback } from 'react';
import { AgentTaskUseCase } from './contexts/types';
import AgentTaskWidgetMock from './AgentTaskWidgetMock';
import AgentTaskWireframeWrapper from './AgentTaskWireframeWrapper';
import { AnimatedMouseCursor, SimulatedMenuBar } from '../shared';

interface AgentTaskPanelProps {
  /** The use case to render */
  useCase: AgentTaskUseCase;
  /** Current animation time in seconds */
  currentTime: number;
  /** Whether drawing animation has started */
  isDrawing: boolean;
}

/**
 * AgentTaskPanel - Generic panel for rendering any AgentTask use case.
 * Uses unified AgentTaskWidgetMock for smooth state transitions.
 * Delegates context rendering to the use case's ContextComponent.
 */
const AgentTaskPanel = ({
  useCase,
  currentTime,
  isDrawing,
}: AgentTaskPanelProps) => {
  // Navigation state for context components
  const [navigationPath, setNavigationPath] = useState<string[]>([]);
  // File viewing state - shared between context and widget
  const [viewingFile, setViewingFile] = useState<string | null>(null);
  // Active tab state for browser-based demos
  const [activeTab, setActiveTab] = useState<string | null>(null);
  
  // Refs for calculating cursor target positions
  const containerRef = useRef<HTMLDivElement>(null);
  const keyboardIconRef = useRef<HTMLElement | null>(null);
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const [cursorTargetPosition, setCursorTargetPosition] = useState<{ x: number; y: number } | null>(null);
  const [widgetCenterPosition, setWidgetCenterPosition] = useState<{ x: number; y: number } | null>(null);
  
  // Track maximum height achieved (high water mark) to prevent shrinking during transitions
  const [maxHeight, setMaxHeight] = useState<number>(0);
  const widgetWrapperRef = useRef<HTMLDivElement>(null);
  
  // Callback ref for keyboard icon
  const handleKeyboardIconRef = useCallback((element: HTMLElement | null) => {
    keyboardIconRef.current = element;
  }, []);
  
  // Callback ref for widget container (drop zone target)
  const handleWidgetContainerRef = useCallback((element: HTMLDivElement | null) => {
    widgetContainerRef.current = element;
  }, []);
  
  // Calculate cursor target positions whenever layout changes
  useEffect(() => {
    const calculatePositions = () => {
      if (!containerRef.current) {
        setCursorTargetPosition(null);
        setWidgetCenterPosition(null);
        return;
      }
      
      const containerRect = containerRef.current.getBoundingClientRect();
      
      // Calculate keyboard icon position
      if (keyboardIconRef.current) {
        const iconRect = keyboardIconRef.current.getBoundingClientRect();
        const x = ((iconRect.left + iconRect.width / 2 - containerRect.left) / containerRect.width) * 100;
        const y = ((iconRect.top + iconRect.height / 2 - containerRect.top) / containerRect.height) * 100;
        setCursorTargetPosition({ x, y });
      } else {
        setCursorTargetPosition(null);
      }
      
      // Calculate widget center position (for drag-drop target)
      if (widgetContainerRef.current) {
        const widgetRect = widgetContainerRef.current.getBoundingClientRect();
        const x = ((widgetRect.left + widgetRect.width / 2 - containerRect.left) / containerRect.width) * 100;
        const y = ((widgetRect.top + widgetRect.height / 2 - containerRect.top) / containerRect.height) * 100;
        setWidgetCenterPosition({ x, y });
      } else {
        setWidgetCenterPosition(null);
      }
    };
    
    // Calculate on mount and when refs change
    calculatePositions();
    
    // Recalculate on resize
    window.addEventListener('resize', calculatePositions);
    
    // Use a short interval to catch layout changes from animations
    const interval = setInterval(calculatePositions, 100);
    
    return () => {
      window.removeEventListener('resize', calculatePositions);
      clearInterval(interval);
    };
  }, [isDrawing]);

  const phase = useCase.getPhase(currentTime);
  const animationStep = useCase.getAnimationStep(currentTime);

  // Reset navigation, file viewing, and active tab when animation restarts
  useEffect(() => {
    if (currentTime < 1) {
      setNavigationPath([]);
      setViewingFile(null);
      setActiveTab(null);
      // Note: maxHeight is NOT reset here - keep consistent sizing during replays
    }
  }, [currentTime]);
  
  // Reset max height only when switching to a different use case (tab)
  useEffect(() => {
    setMaxHeight(0);
  }, [useCase.id]);

  // Get phase-specific data
  const transcription = useCase.getTranscript(currentTime);
  const stepInfo = useCase.getStep(currentTime);

  // Get reference paths if the use case supports drag-and-drop
  const referencePaths = useCase.getReferencePaths?.(currentTime) || [];
  const isDraggingOver = useCase.isDraggingOver?.(currentTime) || false;

  // Get visible tabs if the use case supports browser tabs
  const visibleTabs = useCase.getVisibleTabs?.(currentTime) || [];
  
  // Get typed text if the use case is text-entry mode
  const typedText = useCase.getTypedText?.(currentTime) || '';
  
  // Check if we're currently in the text-entry UI (after clicking keyboard icon)
  const isTextEntryActive = useCase.getIsTextEntryActive?.(currentTime) || false;

  // Map phase to widget state
  const getWidgetState = (): 'idle' | 'capture' | 'text-entry' | 'processing' | 'complete' => {
    // Text entry mode: starts as 'capture', transitions to 'text-entry' after keyboard click
    if (phase === 'capture' && useCase.isTextEntryMode && isTextEntryActive) return 'text-entry';
    if (phase === 'capture') return 'capture';
    if (phase === 'processing') return 'processing';
    if (phase === 'complete') return 'complete';
    return 'idle';
  };

  // Show widget after idle phase
  const showWidget = phase !== 'idle';
  const isComplete = phase === 'complete';

  // Track widget height and maintain high water mark to prevent jumpiness during transitions
  useEffect(() => {
    if (!widgetWrapperRef.current) return;
    
    const observeHeight = () => {
      if (widgetWrapperRef.current) {
        const currentHeight = widgetWrapperRef.current.scrollHeight;
        setMaxHeight(prev => Math.max(prev, currentHeight));
      }
    };
    
    // Use ResizeObserver to track height changes
    const resizeObserver = new ResizeObserver(observeHeight);
    resizeObserver.observe(widgetWrapperRef.current);
    
    // Initial measurement
    observeHeight();
    
    return () => resizeObserver.disconnect();
  }, [showWidget]);

  // Navigation handler for context components
  const handleNavigate = (path: string[]) => {
    setNavigationPath(path);
  };

  // File open handler - opens file viewer
  const handleFileOpen = (fileName: string) => {
    setViewingFile(fileName);
  };

  // Close file viewer
  const handleCloseFile = () => {
    setViewingFile(null);
  };

  // Folder select from widget (click on folder in result)
  const handleFolderSelect = (folderName: string) => {
    if (phase === 'complete') {
      const cleanName = folderName.replace(/\/$/, '');
      // Navigate into folder - needs 'Desktop' as root for proper depth calculation
      setNavigationPath(['Desktop', cleanName]);
    }
  };

  // File select from widget - opens file viewer
  const handleFileSelect = (fileName: string) => {
    setViewingFile(fileName);
  };

  // Link click from widget - changes active tab
  const handleLinkClick = (linkId: string) => {
    setActiveTab(linkId);
  };

  // Tab change from context component (clicking browser tabs)
  const handleTabChange = (tabId: string) => {
    setActiveTab(tabId);
  };

  // Get the context component from the use case
  const ContextComponent = useCase.ContextComponent;

  // Cursor animation for text-entry mode (clicking keyboard icon)
  const getKeyboardCursorState = () => {
    // Only show cursor for text-entry mode use cases, before text entry is active
    if (!useCase.isTextEntryMode || !cursorTargetPosition) {
      return { isVisible: false, position: { x: 50, y: 50 }, isClicking: false };
    }
    
    // Step 1: Cursor appears, moving toward keyboard icon
    // Step 2: Cursor clicks keyboard icon
    // Step 3+: Cursor fades out (text entry active)
    
    if (animationStep < 1) {
      return { isVisible: false, position: { x: 30, y: 30 }, isClicking: false };
    }
    
    if (animationStep >= 1 && animationStep < 2) {
      // Moving toward keyboard icon
      return { isVisible: true, position: cursorTargetPosition, isClicking: false };
    }
    
    if (animationStep >= 2 && animationStep < 3) {
      // Clicking
      return { isVisible: true, position: cursorTargetPosition, isClicking: true };
    }
    
    // After click, fade out
    return { isVisible: false, position: cursorTargetPosition, isClicking: false };
  };
  
  const keyboardCursorState = getKeyboardCursorState();
  
  // Cursor animation for drag-drop mode (dragging folder to widget)
  // Folder position is at ~3%, 5% of the context column (left half on desktop)
  // On desktop grid, context is left 50%, so folder is at ~1.5% of panel
  const getDragCursorState = () => {
    // Only show for use cases with drag-drop (getReferencePaths defined)
    const hasDragDrop = !!useCase.getReferencePaths;
    if (!hasDragDrop || !widgetCenterPosition) {
      return { isVisible: false, position: { x: 5, y: 10 }, isDragging: false, isClicking: false };
    }
    
    // Folder start position - on desktop, context is left column (50% of panel width)
    // Folder at x:3, y:5 in context = x:1.5, y:5 in panel on desktop
    // We use 3% since on mobile the context takes full width
    const folderX = 3;
    const folderY = 8;
    
    // Step 0: cursor not visible
    if (animationStep < 1) {
      return { isVisible: false, position: { x: folderX, y: folderY }, isDragging: false, isClicking: false };
    }
    // Step 1: cursor appears near folder
    if (animationStep < 2) {
      return { isVisible: true, position: { x: folderX + 3, y: folderY + 5 }, isDragging: false, isClicking: false };
    }
    // Step 2: cursor clicks folder
    if (animationStep < 3) {
      return { isVisible: true, position: { x: folderX + 2, y: folderY + 3 }, isDragging: false, isClicking: true };
    }
    // Step 3-4: dragging with arc animation
    if (animationStep < 5) {
      const dragProgress = Math.min(1, Math.max(0, animationStep - 3));
      const startX = folderX + 2;
      const startY = folderY + 3;
      const endX = widgetCenterPosition.x;
      const endY = widgetCenterPosition.y;
      
      // Arc animation
      const arcY = -15;
      const t = dragProgress;
      const x = startX + (endX - startX) * t;
      const y = startY + (endY - startY) * t + arcY * Math.sin(t * Math.PI);
      
      return { isVisible: true, position: { x, y }, isDragging: true, isClicking: false };
    }
    // Step 5: just dropped
    if (animationStep < 5.5) {
      return { isVisible: true, position: widgetCenterPosition, isDragging: false, isClicking: false };
    }
    // After drop, fade out
    return { isVisible: false, position: widgetCenterPosition, isDragging: false, isClicking: false };
  };
  
  const dragCursorState = getDragCursorState();
  const hasDragAnimation = !!useCase.getReferencePaths;
  
  // Recording state for menu bar
  const isRecording = phase === 'capture';

  return (
    <div className="relative flex flex-col h-full">
      {/* Simulated Menu Bar - edge to edge */}
      <SimulatedMenuBar isRecording={isRecording} />
      
      {/* Main content area with padding */}
      <div ref={containerRef} className="relative flex-1 grid grid-cols-2 gap-4 min-h-[500px] overflow-visible p-4 sm:p-6">
        {/* Left: Context component - handles all context-specific rendering */}
        {/* overflow-visible allows desktop files to span across both columns */}
      <div 
          className={`transition-all duration-700 ease-out min-h-[280px] lg:min-h-0 overflow-visible ${
          isDrawing ? 'opacity-100' : 'opacity-0'
        }`}
      >
        <ContextComponent 
          animationStep={animationStep}
          navigationPath={navigationPath}
          onNavigate={handleNavigate}
          onFileOpen={handleFileOpen}
          viewingFile={viewingFile}
          onCloseFile={handleCloseFile}
          visibleTabs={visibleTabs}
          {...(activeTab && { activeTab })}
          onTabChange={handleTabChange}
        />
      </div>

        {/* Right: AgentTask Widget */}
        <div 
          ref={widgetWrapperRef}
          className={`flex items-start justify-center transition-all duration-500 ${
            showWidget ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8'
          }`}
          style={{ minHeight: maxHeight > 0 ? `${maxHeight}px` : undefined }}
        >
          <AgentTaskWireframeWrapper 
            isDrawing={isDrawing && showWidget} 
            isComplete={isComplete}
          >
            <AgentTaskWidgetMock
              state={getWidgetState()}
              transcription={transcription}
              commandText={useCase.commandText}
              typedText={typedText}
              currentStepLabel={stepInfo.label}
              completedSteps={useCase.completedSteps || []}
              resultText={useCase.resultSummary}
              structuredFiles={useCase.structuredFiles || []}
              structuredLinks={useCase.structuredLinks || []}
              referencePaths={referencePaths}
              isDraggingOver={isDraggingOver}
              onFolderSelect={handleFolderSelect}
              onFileSelect={handleFileSelect}
              onLinkClick={handleLinkClick}
              keyboardIconRef={handleKeyboardIconRef}
              widgetContainerRef={handleWidgetContainerRef}
            />
          </AgentTaskWireframeWrapper>
        </div>
        
        {/* Animated cursor for keyboard click (text-entry mode) */}
        {useCase.isTextEntryMode && (
          <AnimatedMouseCursor
            isVisible={keyboardCursorState.isVisible}
            position={keyboardCursorState.position}
            isDragging={false}
            isClicking={keyboardCursorState.isClicking}
          />
        )}
        
        {/* Animated cursor for drag-drop (automatic intake mode) */}
        {hasDragAnimation && (
          <AnimatedMouseCursor
            isVisible={dragCursorState.isVisible}
            position={dragCursorState.position}
            isDragging={dragCursorState.isDragging}
            isClicking={dragCursorState.isClicking}
            draggedItem={
              <img 
                src="/images/icons/folder.png" 
                alt="Folder"
                className="w-12 h-12 object-contain"
              />
            }
          />
        )}
      </div>
    </div>
  );
};

export default AgentTaskPanel;
