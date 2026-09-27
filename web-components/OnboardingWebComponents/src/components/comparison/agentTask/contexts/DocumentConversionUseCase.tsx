"use client";

import React from 'react';
import { AgentTaskUseCase, AgentTaskPhase, ReferencePath } from './types';
import DocumentConversionContext from './DocumentConversionContext';

// ============================================================================
// TIMING CONSTANTS
// ============================================================================

const TIMINGS = {
  CAPTURE_START: 2,
  CURSOR_APPEAR: 2.5,     // Cursor fades in
  CURSOR_CLICK: 3.5,      // Cursor clicks folder (slower approach)
  DRAG_START: 4.0,        // Folder attaches to cursor (pause after click)
  DRAG_OVER: 8.0,         // Position update sent (CSS transition takes 1.5s to arrive)
  DROP: 10.0,             // Folder dropped after cursor visually arrives (~8.0 + 1.5s transition + pause)
  CURSOR_FADE: 10.5,      // Cursor fades out
  CAPTURE_END: 13,        // Extended capture phase
  PROCESSING_START: 13,
  STEP_1: 16,             // Resolving reference materials (more initial processing time)
  STEP_2: 19,             // Reading template and requirements
  STEP_3: 23,             // Creating request submission
  STEP_4: 26,             // Verifying file created
  COMPLETE: 30,
};

const DURATION = 34;

// ============================================================================
// CONTENT
// ============================================================================

const COMMAND_TEXT = "Using the documents in this folder, create a request submission that combines the client requirements with the template format.";

const RESULT_SUMMARY = `Done! I've created 'External_Provider_Referral_Request_Submission.md' in your Harmony Home Care folder.

The document combines the client's feature requirements (External Provider Incident Report) with the standard submission template format, including:

- Executive summary of the request
- Detailed requirements breakdown
- Technical specifications
- Implementation timeline estimates
- Success criteria and acceptance testing plan`;

const COMPLETED_STEPS = [
  "Resolved reference materials: Harmony Home Care/",
  "Read Provider_Referral_Template.md (template format)",
  "Read Client_Feature_Request.md (requirements)",
  "Created External_Provider_Referral_Request_Submission.md",
  "Verified file created successfully (8.4 KB)",
];

const STRUCTURED_FILES = [
  { name: "Harmony Home Care/", isFolder: true, isInput: true },
  { name: "External_Provider_Referral_Request_Submission.md", isFolder: false },
];

const REFERENCE_FOLDER: ReferencePath = {
  name: "Harmony Home Care/",
  isFolder: true,
};

// ============================================================================
// PROCESSING STEPS
// ============================================================================

const STEPS = [
  { label: "Resolving reference materials..." },
  { label: "Reading template and requirements..." },
  { label: "Creating request submission document..." },
  { label: "Verifying file created successfully" },
];

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const getPhase = (time: number): AgentTaskPhase => {
  if (time < TIMINGS.CAPTURE_START) return 'idle';
  if (time < TIMINGS.CAPTURE_END) return 'capture';
  if (time < TIMINGS.COMPLETE) return 'processing';
  return 'complete';
};

const getTranscript = (time: number): string => {
  // During capture phase, progressively reveal the speech
  if (time < TIMINGS.CAPTURE_START) return "";
  if (time >= TIMINGS.CAPTURE_END) return COMMAND_TEXT;
  
  // Calculate progress through capture phase
  const captureProgress = (time - TIMINGS.CAPTURE_START) / (TIMINGS.CAPTURE_END - TIMINGS.CAPTURE_START);
  // Return progressively more of the text
  const charsToShow = Math.floor(captureProgress * COMMAND_TEXT.length);
  return COMMAND_TEXT.substring(0, charsToShow);
};

const getCaptureProgress = (time: number): number => {
  if (time < TIMINGS.CAPTURE_START) return 0;
  if (time >= TIMINGS.CAPTURE_END) return 1;
  return (time - TIMINGS.CAPTURE_START) / (TIMINGS.CAPTURE_END - TIMINGS.CAPTURE_START);
};

const getStep = (time: number): { index: number; label: string } => {
  if (time < TIMINGS.STEP_1) return { index: 0, label: STEPS[0]?.label ?? "Processing..." };
  if (time < TIMINGS.STEP_2) return { index: 1, label: STEPS[1]?.label ?? "Processing..." };
  if (time < TIMINGS.STEP_3) return { index: 2, label: STEPS[2]?.label ?? "Processing..." };
  if (time < TIMINGS.STEP_4) return { index: 3, label: STEPS[3]?.label ?? "Processing..." };
  return { index: 3, label: STEPS[3]?.label ?? "Processing..." };
};

const getAnimationStep = (time: number): number => {
  // Animation steps for the context component
  // 0: Initial desktop
  // 1: Cursor appears
  // 2: Cursor clicks folder
  // 3: Dragging (0-1 progress within step)
  // 4: Over widget (drop overlay)
  // 5: Dropped
  // 6: Processing
  // 7: Complete - show new file
  
  if (time < TIMINGS.CURSOR_APPEAR) return 0;
  if (time < TIMINGS.CURSOR_CLICK) return 1;
  if (time < TIMINGS.DRAG_START) return 2;
  if (time < TIMINGS.DRAG_OVER) {
    // Interpolate during drag
    const progress = (time - TIMINGS.DRAG_START) / (TIMINGS.DRAG_OVER - TIMINGS.DRAG_START);
    return 3 + progress;
  }
  if (time < TIMINGS.DROP) return 4;
  if (time < TIMINGS.CAPTURE_END) return 5;
  if (time < TIMINGS.COMPLETE) return 6;
  return 7;
};

// Drag-and-drop reference functions
const getReferencePaths = (time: number): ReferencePath[] => {
  // Reference appears after drop
  if (time >= TIMINGS.DROP) {
    return [REFERENCE_FOLDER];
  }
  return [];
};

const isDraggingOver = (time: number): boolean => {
  // Drop overlay visible when cursor is over widget
  return time >= TIMINGS.DRAG_OVER && time < TIMINGS.DROP;
};

// ============================================================================
// USE CASE EXPORT
// ============================================================================

export const documentGenerationUseCase: AgentTaskUseCase = {
  id: 'automatic-request-intake',
  label: 'Automatic Request Intake',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  ),
  
  duration: DURATION,
  getPhase,
  
  // Capture
  getTranscript,
  getCaptureProgress,
  
  // Processing
  getStep,
  totalSteps: STEPS.length,
  steps: STEPS,
  
  // Complete
  commandText: COMMAND_TEXT,
  resultSummary: RESULT_SUMMARY,
  completedSteps: COMPLETED_STEPS,
  structuredFiles: STRUCTURED_FILES,
  
  // Drag-and-drop references
  getReferencePaths,
  isDraggingOver,
  
  // Context
  ContextComponent: DocumentConversionContext,
  getAnimationStep,
};

export default documentGenerationUseCase;

// Export timing constants for use by the context component
export { TIMINGS };
