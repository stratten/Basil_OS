"use client";

import React from 'react';
import { AgentTaskUseCase, AgentTaskPhase } from './types';
import ProductSearchContext from './ProductSearchContext';

// ============================================================================
// TIMING CONSTANTS
// ============================================================================

const TIMINGS = {
  // Capture phase (standard agentTask widget first)
  WIDGET_APPEAR: 1,
  KEYBOARD_CLICK: 3,       // User clicks keyboard icon
  
  // Text entry phase
  TEXT_ENTRY_START: 3.5,   // Transition to text entry mode
  TEXT_START: 4.5,         // Start typing animation
  TEXT_END: 9.5,           // Finish typing (5 seconds of typing)
  SEND_CLICK: 10,          // Click send button
  
  // Processing phase
  PROCESSING_START: 10.5,
  STEP_1: 12.5,            // Researching stain removal solutions... (Browser Tab 1 opens)
  STEP_2: 15.5,            // Found enzyme-based cleaners... (Tab 2 opens)
  STEP_3: 18.5,            // Comparing products and prices... (Tab 3 opens)
  STEP_4: 21.5,            // Opening product listings...
  
  // Complete
  COMPLETE: 24.5,
};

const DURATION = 30;

// ============================================================================
// COMMAND TEXT
// ============================================================================

const COMMAND_TEXT = "I spilled red wine on my office chair, because I'm a degenerate. Can you research the best stain removers and open links to buy them on Emazon?";

// ============================================================================
// RESULT DATA
// ============================================================================

const RESULT_SUMMARY = `I found 3 highly-rated stain removers that work well on red wine stains in fabric upholstery:

1. {{link:revolve:Revolve Triple Oxi}} ($8.99) - Best for deep-set stains, enzyme-based formula
2. {{link:mr-mean:Mr. Mean Multi-Surface}} ($12.49) - Versatile all-purpose cleaner
3. {{link:oxyfresh:OxyFresh Powder}} ($14.99) - Oxygen-powered, safe for all fabrics

I've opened each product page in your browser. For best results with red wine, blot (don't rub) the stain first, then apply the enzyme cleaner and let it sit for 5-10 minutes before blotting again.`;

const COMPLETED_STEPS = [
  "Analyzed stain type: red wine on fabric upholstery",
  "Searched for enzyme-based and oxygen cleaners",
  "Filtered by customer ratings (4+ stars)",
  "Compared prices across 12 products",
  "Selected top 3 recommendations",
  "Opened product pages in browser",
];

// Links that appear in result and control browser tabs
const STRUCTURED_LINKS = [
  { id: 'revolve', label: 'Revolve Triple Oxi Advanced - $8.99', url: 'amazon.com/revolve-triple-oxi' },
  { id: 'mr-mean', label: 'Mr. Mean Multi-Surface Cleaner - $12.49', url: 'amazon.com/mr-mean-cleaner' },
  { id: 'oxyfresh', label: 'OxyFresh Stain Remover Powder - $14.99', url: 'amazon.com/oxyfresh-powder' },
];

// ============================================================================
// PHASE AND TIMING FUNCTIONS
// ============================================================================

const getPhase = (time: number): AgentTaskPhase => {
  if (time < TIMINGS.WIDGET_APPEAR) return 'idle';
  if (time < TIMINGS.PROCESSING_START) return 'capture'; // Includes both voice capture and text-entry
  if (time < TIMINGS.COMPLETE) return 'processing';
  return 'complete';
};

// Returns true when the widget should show text-entry UI instead of voice capture UI
// (Also used to hide the speech overlay when user clicks keyboard icon)
const getIsTextEntryActive = (time: number): boolean => {
  // Hide speech overlay right when keyboard is clicked, not when transition completes
  return time >= TIMINGS.KEYBOARD_CLICK && time < TIMINGS.PROCESSING_START;
};

// Get how much of the command text to show (animated typing)
const getTypedText = (time: number): string => {
  if (time < TIMINGS.TEXT_START) return '';
  if (time >= TIMINGS.TEXT_END) return COMMAND_TEXT;
  
  // Calculate progress through typing
  const typingDuration = TIMINGS.TEXT_END - TIMINGS.TEXT_START;
  const elapsed = time - TIMINGS.TEXT_START;
  const progress = elapsed / typingDuration;
  
  // Show characters based on progress
  const charsToShow = Math.floor(progress * COMMAND_TEXT.length);
  return COMMAND_TEXT.substring(0, charsToShow);
};

const getTranscript = (time: number): string => {
  // In text-entry mode, we don't use transcription - return the typed text
  return getTypedText(time);
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
const getCaptureProgress = (_time: number): number => {
  // Not used for text entry mode
  return 0;
};

const getStep = (time: number): { index: number; label: string } => {
  if (time < TIMINGS.STEP_1) return { index: 0, label: "Researching stain removal solutions..." };
  if (time < TIMINGS.STEP_2) return { index: 1, label: "Found enzyme-based cleaners for wine stains..." };
  if (time < TIMINGS.STEP_3) return { index: 2, label: "Comparing products and prices..." };
  if (time < TIMINGS.STEP_4) return { index: 3, label: "Opening product listings..." };
  return { index: 4, label: "Complete" };
};

// Animation step for context component (controls browser tab opening)
const getAnimationStep = (time: number): number => {
  if (time < TIMINGS.WIDGET_APPEAR) return 0;
  if (time < TIMINGS.KEYBOARD_CLICK) return 1;    // Standard capture widget visible
  if (time < TIMINGS.TEXT_ENTRY_START) return 2;  // Keyboard icon clicked
  if (time < TIMINGS.TEXT_START) return 3;        // Text entry mode, ready to type
  if (time < TIMINGS.SEND_CLICK) return 4;        // Typing in progress
  if (time < TIMINGS.PROCESSING_START) return 5;  // Send clicked
  if (time < TIMINGS.STEP_1) return 6;            // Processing started
  if (time < TIMINGS.STEP_2) return 7;            // Tab 1 opens
  if (time < TIMINGS.STEP_3) return 8;            // Tab 2 opens
  if (time < TIMINGS.STEP_4) return 9;            // Tab 3 opens
  if (time < TIMINGS.COMPLETE) return 10;         // All tabs open
  return 11;                                       // Complete
};

// Determine which tabs are visible based on animation step
const getVisibleTabs = (time: number): string[] => {
  const step = getAnimationStep(time);
  if (step < 7) return [];           // No tabs until processing step 1
  if (step === 7) return ['revolve'];
  if (step === 8) return ['revolve', 'mr-mean'];
  return ['revolve', 'mr-mean', 'oxyfresh'];
};

// ============================================================================
// USE CASE EXPORT
// ============================================================================

export const productSearchUseCase: AgentTaskUseCase = {
  id: 'product-search',
  label: 'Product Search',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
    </svg>
  ),
  
  duration: DURATION,
  getPhase,
  getTranscript,
  getCaptureProgress,
  getStep,
  totalSteps: 4,
  steps: [
    { label: "Researching stain removal solutions..." },
    { label: "Found enzyme-based cleaners..." },
    { label: "Comparing products and prices..." },
    { label: "Opening product listings..." },
  ],
  
  commandText: COMMAND_TEXT,
  resultSummary: RESULT_SUMMARY,
  completedSteps: COMPLETED_STEPS,
  structuredLinks: STRUCTURED_LINKS,
  
  // Text entry mode - starts with voice capture, transitions to text entry
  isTextEntryMode: true,
  getTypedText,
  getIsTextEntryActive,
  getVisibleTabs,
  
  ContextComponent: ProductSearchContext,
  getAnimationStep,
};

export default productSearchUseCase;
