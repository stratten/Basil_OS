"use client";

import React from 'react';
import { ContextComponentProps } from './types';
import { MockFinderWindow, MockTextViewer } from '../../shared';

// ============================================================================
// FOLDER FILES - Files in the Harmony Home Care folder
// ============================================================================

const WORKSPACE_FILES = [
  { name: 'Provider_Referral_Template.md', type: 'txt', dateModified: 'Nov 15, 2025', size: '4.2 KB', kind: '.md' },
  { name: 'Client_Feature_Request.md', type: 'txt', dateModified: 'Nov 18, 2025', size: '6.8 KB', kind: '.md' },
];

const OUTPUT_FILE = {
  name: 'External_Provider_Referral_Request_Submission.md',
  type: 'txt',
  dateModified: 'Today',
  size: '8.4 KB',
  kind: '.md',
};

// ============================================================================
// FILE CONTENTS
// ============================================================================

const TEMPLATE_CONTENT = `# Harmony Home Care - Request Submission Template

**Instructions:** Complete this template and submit by the last Friday of each month for consideration in the following month's planning meeting. The more detail you provide, the better we can estimate effort and identify potential impacts to other departments.

---

## Request Information

| Field | Response |
|-------|----------|
| **Submitted By** | [Your name] |
| **Department** | [HR / Intake / Quality Assurance / Case Management / Other] |
| **Submission Date** | [Date] |
| **Target Month** | [Month you'd like this completed] |
| **Priority** | [High / Medium / Low] |

---

## Problem & Solution

| Field | Response |
|-------|----------|
| **What problem are you solving?** | [Be specific about current pain points] |
| **Why does this matter?** | [Business value - time saved, errors reduced, etc.] |
| **Who's affected?** | [Which departments, roles, or people will use this?] |
| **What does success look like?** | [How will you know this is working?] |

---

## Cross-Departmental Impact

| Field | Response |
|-------|----------|
| **Have you talked to other departments?** | [Yes / No - If yes, who?] |
| **Does this affect data other departments use?** | [Yes / No - describe] |
| **Does this change existing workflows?** | [Yes / No - describe] |

---

## Testing & Ownership

| Field | Response |
|-------|----------|
| **Who will test this?** | [Name and role] |
| **When can you test?** | [Timeframe] |
| **Do you have sandbox access?** | [Yes / No / Need reset] |

---

**Submit completed template to:** requests@harmonyhomecare.com`;

const CLIENT_REQUEST_CONTENT = `GENERATE REFERRAL TO EXTERNAL PROVIDER FROM INCIDENT REPORT
IN SALESFORCE

TECHNICAL SPECIFICATION REQUEST
JANUARY 2026

---

## A. Build a Referral to External Provider Form from Incident Report

### 1. Current State

The Clinical Quality environment in Salesforce does not have the ability to generate a Referral Form to an External Provider. However, the Intake environment has this Form. Clinical Quality would like to create this form using the existing Intake format but with fields customized for clinical operations.

### 2. Future State Requirements

1. **Referral Generation** - Accessible within the Incident Report module
2. **Auto-email** - Generates email to receiving provider with CC to Clinical Team and assigned Case Manager
3. **HHAExchange Data Replication** - Auto-populate from HHA Exchange:
   - Patient Name
   - Patient service address
   - Telephone number(s)
   - Date of Birth
   - Medicare Number
   - Event Detail/Description (from Incident Report)

4. **Custom Fields for Manual Entry:**
   - Name of Decision maker (if patient cannot provide consent)
   - Relationship with patient
   - Telephone number of Decision Maker
   - Best day/time to call

5. **Email Distribution Lists:**
   - Primary: intake@healthprovider.com
   - Team-based CC lists based on patient assignment
   - Assigned Case Manager auto-included

6. **Referral Status Options:**
   - OPEN
   - Appointment Scheduled
   - CLOSED

7. **Reminder Alerts:**
   - Auto-generated starting Day 7 for open referrals
   - Daily until status marked CLOSED
   - Include patient details and link to referral record

8. **Reports & Dashboard:**
   - Aggregate data on all fields for custom reports`;

const OUTPUT_CONTENT = `# Harmony Home Care - Request Submission

**Instructions:** Complete this template and submit by the last Friday of each month for consideration in the following month's planning meeting.

---

## Request Information

| Field | Response |
|-------|----------|
| **Submitted By** | Clinical Quality Team |
| **Department** | Quality Assurance / Clinical Operations |
| **Submission Date** | January 2026 |
| **Target Month** | February 2026 |
| **Priority** | High |

---

## Problem & Solution

| Field | Response |
|-------|----------|
| **What problem are you solving?** | The Clinical Quality environment in Salesforce currently does not have the ability to generate a Referral Form to an External Provider from within the Incident Report module. Currently, staff must manually create referrals outside the system, leading to inefficiencies, potential errors, and lack of tracking/reporting capabilities. |
| **Why does this matter?** | • Eliminate manual referral creation, saving significant time for clinical staff<br>• Ensure consistent referral formatting and complete information<br>• Automatically route referrals to appropriate external providers and internal teams<br>• Enable tracking of referral status from generation through closure<br>• Provide automated follow-up reminders<br>• Create audit trail and reporting capabilities for compliance |
| **Who's affected?** | • Clinical Quality team members (primary users)<br>• Case Managers (will receive alerts and manage referrals)<br>• External providers (will receive referral emails)<br>• Clinical leadership |
| **What does success look like?** | Users can generate a referral directly from an Incident Report with one click. The system auto-populates patient demographic data, allows manual entry of additional fields, and automatically emails the completed referral with appropriate CC to the internal clinical team. Users can track referral status and receive automated reminders. |

---

## Cross-Departmental Impact

| Field | Response |
|-------|----------|
| **Have you talked to other departments?** | Yes - This request involves Case Management teams. Coordination with Intake team needed to understand current functionality. |
| **Does this affect data other departments use?** | Yes - Case Managers will receive automated alerts. The feature pulls demographic data from HHAExchange integration. |
| **Does this change existing workflows?** | Yes - Creates new workflow for Clinical Quality to generate referrals from Incident Reports. Case Managers will have new responsibilities to update status. |

---

## Testing & Ownership

| Field | Response |
|-------|----------|
| **Who will test this?** | Clinical Quality team lead and designated Case Managers |
| **When can you test?** | Available for testing during February 2024 |
| **Do you have sandbox access?** | [To be confirmed] |

---

## Additional Context

**Key Technical Requirements:**

**Data Integration:**
• HHAExchange demographic data replication: Patient Name, Service Address, Telephone Numbers, Date of Birth, Medicare Number
• Incident Report data auto-population: Event Detail/Description

**Custom Fields for Manual Entry:**
• Decision maker name (if patient cannot consent)
• Relationship with patient
• Decision maker telephone
• Best day/time to call

**Status Tracking:**
• Dropdown: Open / Appointment Scheduled / Closed
• Status change triggers alert emails to internal team

**Automated Reminders:**
• Start on Day 7 for Open referrals, daily thereafter until Closed
• Include: Patient Name, Event Type, Date, Details, Link to Record

---

**Submit completed template to:** requests@harmonyhomecare.com`;

// ============================================================================
// DESKTOP FILES - Organized in top-left corner (like a real desktop)
// ============================================================================

interface DesktopItem {
  id: string;
  name: string;
  type: 'folder' | 'file';
  fileType?: string;
  x: number; // percentage
  y: number; // percentage
}

// Stacked neatly in top-left area
const DESKTOP_ITEMS: DesktopItem[] = [
  { id: 'workspace', name: 'Harmony Home Care', type: 'folder', x: 3, y: 5 },
  { id: 'notes', name: 'Meeting Notes.txt', type: 'file', fileType: 'txt', x: 3, y: 18 },
  { id: 'report', name: 'Q4 Report.pdf', type: 'file', fileType: 'pdf', x: 3, y: 31 },
  { id: 'screenshot', name: 'Screenshot 2025-01-15.png', type: 'file', fileType: 'screenshot', x: 3, y: 44 },
  { id: 'invoice', name: 'Invoice_2025_001.xlsx', type: 'file', fileType: 'xlsx', x: 3, y: 57 },
];

// ============================================================================
// COMPONENT
// ============================================================================

const DocumentConversionContext: React.FC<ContextComponentProps> = ({
  animationStep,
  navigationPath = [],
  onNavigate,
  onFileOpen,
  viewingFile,
  onCloseFile,
}) => {
  // Determine what to show based on animation step
  const isComplete = animationStep >= 7;
  
  // Get file content based on filename
  const getFileContent = (fileName: string): string => {
    if (fileName === 'Provider_Referral_Template.md') return TEMPLATE_CONTENT;
    if (fileName === 'Client_Feature_Request.md') return CLIENT_REQUEST_CONTENT;
    if (fileName === 'External_Provider_Referral_Request_Submission.md') return OUTPUT_CONTENT;
    return '';
  };
  
  // Handle file open from Finder - uses controlled callback from parent
  const handleFileOpen = (fileName: string) => {
    if (onFileOpen) onFileOpen(fileName);
  };
  
  // Determine if workspace folder is being dragged (show darkened/selected state)
  // Cursor animation is now handled at panel level
  const isDragging = animationStep >= 3 && animationStep < 5;
  
  // Files to show in Finder window
  const getFinderFiles = () => {
    const files = [...WORKSPACE_FILES];
    if (isComplete) {
      files.push(OUTPUT_FILE);
    }
    return files;
  };
  
  return (
    <div className="relative w-full h-full min-h-[400px]">
      {/* Desktop icons layer */}
      <div className="absolute inset-0">
        {DESKTOP_ITEMS.map((item) => {
          // When dragging the workspace folder, show it with darkened/selected appearance
          const isBeingDragged = item.id === 'workspace' && isDragging;
          
          return (
            <div
              key={item.id}
              className="absolute flex flex-col items-center gap-1 cursor-pointer"
              style={{
                left: `${item.x}%`,
                top: `${item.y}%`,
                opacity: isBeingDragged ? 0.5 : 1,
                transition: 'opacity 0.3s ease-out',
              }}
              onDoubleClick={() => {
                if (item.type === 'folder' && onNavigate) {
                  onNavigate([item.name]);
                }
              }}
            >
              {item.type === 'folder' ? (
                <div className="relative">
                  {/* Selection highlight background when dragging */}
                  {isBeingDragged && (
                    <div 
                      className="absolute inset-0 rounded-lg"
                      style={{ 
                        backgroundColor: 'rgba(0, 122, 255, 0.3)',
                        margin: '-4px',
                        padding: '4px',
                      }}
                    />
                  )}
                  <img 
                    src="/images/icons/folder.png" 
                    alt={item.name}
                    className="w-12 h-12 object-contain relative"
                    style={{ 
                      filter: isBeingDragged 
                        ? 'drop-shadow(0 2px 4px rgba(0,0,0,0.3)) brightness(0.7)' 
                        : 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' 
                    }}
                  />
                </div>
              ) : (
                <img 
                  src={`/images/icons/${getIconForType(item.fileType)}.png`}
                  alt={item.name}
                  className="w-10 h-12 object-contain"
                  style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}
                />
              )}
              <span 
                className="text-[10px] text-white text-center px-1 rounded max-w-[80px] truncate"
                style={{ 
                  textShadow: '0 1px 2px rgba(0,0,0,0.8)',
                  backgroundColor: isBeingDragged ? 'rgba(0, 122, 255, 0.5)' : 'rgba(0,0,0,0.3)',
                }}
              >
                {item.name}
              </span>
            </div>
          );
        })}
      </div>
      
      {/* Finder window - positioned on left side, responsive */}
      <div 
        className="absolute transition-all duration-500"
        style={{
          left: '2%',
          top: '4%',
          width: '96%',
          maxWidth: '400px',
          height: '280px',
          opacity: navigationPath.length > 0 ? 1 : 0,
          transform: navigationPath.length > 0 ? 'translateY(0)' : 'translateY(10px)',
          pointerEvents: navigationPath.length > 0 ? 'auto' : 'none',
        }}
      >
        <MockFinderWindow
          title={navigationPath[0] || 'Harmony Home Care'}
          folders={[]}
          files={getFinderFiles().map(f => ({
            name: f.name,
            dateModified: f.dateModified,
            size: f.size,
            kind: f.kind,
            isFile: true,
          }))}
          currentPath={navigationPath.length > 0 ? navigationPath : ['Harmony Home Care']}
          {...(onNavigate && { onNavigate })}
          onFileOpen={handleFileOpen}
          onClose={() => onNavigate && onNavigate([])}
        />
      </div>
      
      {/* Text file viewer modal */}
      <MockTextViewer
        isOpen={!!viewingFile}
        onClose={onCloseFile || (() => {})}
        fileName={viewingFile || ''}
        content={viewingFile ? getFileContent(viewingFile) : ''}
      />
    </div>
  );
};

// Helper to get icon filename for file type
const getIconForType = (fileType?: string): string => {
  switch (fileType) {
    case 'txt': return 'txt';
    case 'pdf': return 'pdf';
    case 'screenshot': return 'png';
    case 'xlsx': return 'xlsx';
    case 'doc': return 'word-processor';
    default: return 'txt';
  }
};

export default DocumentConversionContext;
