"use client";

import React from 'react';
import { AgentTaskUseCase, AgentTaskPhase } from './types';
import { MockFinderWindow, MockTextViewer } from '../../shared';

// ============================================================================
// TIMING CONSTANTS - Slower, more realistic timing for 7-folder structure
// ============================================================================

// Command is ~41 words, at 7.5 WPS = ~5.5s speech time + 2s buffer = ~7.5s capture duration
const TIMINGS = {
  CAPTURE_START: 2,
  CAPTURE_END: 10,      // Extended for full speech to complete
  PROCESSING_START: 10,
  STEP_1: 10,    // Analyzing 67 files...
  STEP_2: 14,    // Designing folder structure...
  STEP_3: 16,    // Creating 01_Documents/ with 5 subfolders
  STEP_4: 18,    // Creating 02_Work_Projects/ with 3 subfolders
  STEP_5: 19,    // Creating remaining folders...
  STEP_6: 22,    // Moving documents (15 files)
  STEP_7: 25,    // Moving work files (9 files)
  STEP_8: 27,    // Moving data files (12 files)
  STEP_9: 29,    // Moving installers (8 files)
  STEP_10: 32,   // Moving media (18 files)
  STEP_11: 34,   // Moving archives and temp (5 files)
  STEP_12: 36,   // Creating ORGANIZATION_SUMMARY.txt
  COMPLETE: 38,
};

const DURATION = 42;

// ============================================================================
// FOLDER HIERARCHY - Based on actual Basil output
// ============================================================================

export interface DesktopFolder {
  id: string;
  name: string;
  subfolders: SubFolder[];
}

export interface SubFolder {
  id: string;
  name: string;
  parentId: string;
  fileCount: number;
}

export const FOLDER_HIERARCHY: DesktopFolder[] = [
  {
    id: '01_Documents',
    name: '01_Documents',
    subfolders: [
      { id: 'Contracts_Agreements', name: 'Contracts_Agreements', parentId: '01_Documents', fileCount: 6 },
      { id: 'Forms_Templates', name: 'Forms_Templates', parentId: '01_Documents', fileCount: 5 },
      { id: 'Financial_Tax', name: 'Financial_Tax', parentId: '01_Documents', fileCount: 4 },
    ],
  },
  {
    id: '02_Work_Projects',
    name: '02_Work_Projects',
    subfolders: [
      { id: 'Client_Projects', name: 'Client_Projects', parentId: '02_Work_Projects', fileCount: 5 },
      { id: 'Invoices_Reports', name: 'Invoices_Reports', parentId: '02_Work_Projects', fileCount: 4 },
    ],
  },
  {
    id: '03_Data_Files',
    name: '03_Data_Files',
    subfolders: [
      { id: 'CSV_Excel', name: 'CSV_Excel', parentId: '03_Data_Files', fileCount: 12 },
    ],
  },
  {
    id: '04_Software',
    name: '04_Software',
    subfolders: [
      { id: 'Installers', name: 'Installers', parentId: '04_Software', fileCount: 8 },
    ],
  },
  {
    id: '05_Media',
    name: '05_Media',
    subfolders: [
      { id: 'Images', name: 'Images', parentId: '05_Media', fileCount: 18 },
    ],
  },
  {
    id: '06_Archives',
    name: '06_Archives',
    subfolders: [
      { id: 'Compressed_Files', name: 'Compressed_Files', parentId: '06_Archives', fileCount: 3 },
    ],
  },
  {
    id: '07_Temporary',
    name: '07_Temporary',
    subfolders: [
      { id: 'Downloads_Misc', name: 'Downloads_Misc', parentId: '07_Temporary', fileCount: 2 },
    ],
  },
];

// ============================================================================
// STEP DEFINITIONS - More detailed for the new flow
// ============================================================================

const STEPS = [
  { label: "Analyzing 67 files on Desktop..." },
  { label: "Designing folder structure..." },
  { label: "Creating 01_Documents/ with 5 subfolders" },
  { label: "Creating 02_Work_Projects/ with 3 subfolders" },
  { label: "Creating remaining folders (5)..." },
  { label: "Moving documents (15 files)" },
  { label: "Moving work files (9 files)" },
  { label: "Moving data files (12 files)" },
  { label: "Moving installers (8 files)" },
  { label: "Moving media (18 files)" },
  { label: "Moving archives and temp (5 files)" },
  { label: "Creating ORGANIZATION_SUMMARY.txt" },
];

// Completed steps for result display
const COMPLETED_STEPS = [
  "Analyzed 67 files on Desktop",
  "Designed 7-category folder structure with 10 subfolders",
  "Created 01_Documents/ (Contracts, Forms, Financial)",
  "Created 02_Work_Projects/ (Client Projects, Invoices/Reports)",
  "Created 03_Data_Files/ (CSV/Excel)",
  "Created 04_Software/ (Installers)",
  "Created 05_Media/ (Images)",
  "Created 06_Archives/ (Compressed Files)",
  "Created 07_Temporary/ (Downloads/Misc)",
  "Moved 15 documents to 01_Documents/",
  "Moved 9 work files to 02_Work_Projects/",
  "Moved 12 data files to 03_Data_Files/",
  "Moved 8 installers to 04_Software/",
  "Moved 18 media files to 05_Media/",
  "Moved 5 files to 06_Archives/ and 07_Temporary/",
  "Created ORGANIZATION_SUMMARY.txt",
];

// Structured files (folders created + summary)
const STRUCTURED_FILES = [
  { name: "01_Documents/", isFolder: true },
  { name: "02_Work_Projects/", isFolder: true },
  { name: "03_Data_Files/", isFolder: true },
  { name: "04_Software/", isFolder: true },
  { name: "05_Media/", isFolder: true },
  { name: "06_Archives/", isFolder: true },
  { name: "07_Temporary/", isFolder: true },
  { name: "ORGANIZATION_SUMMARY.txt", isFolder: false },
];

// ============================================================================
// DESKTOP FILES DATA - 67 files with realistic names
// ============================================================================

export type FileType = 'screenshot' | 'pdf' | 'doc' | 'dmg' | 'txt' | 'xlsx' | 'zip';

export interface DesktopFile {
  id: string;
  name: string;
  type: FileType;
  x: number;
  y: number;
  targetFolder: string;    // e.g., "01_Documents"
  targetSubfolder: string; // e.g., "Contracts_Agreements"
}

export const DESKTOP_FILES: DesktopFile[] = [
  // Files are randomly distributed across the entire desktop (0-95% x, 0-95% y)
  // This includes the area where the agentTask widget will appear
  
  // === 01_DOCUMENTS - Contracts_Agreements (6 files) ===
  { id: 'ca1', name: 'Consulting Agreement Final.pdf', type: 'pdf', x: 92, y: 8, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },
  { id: 'ca2', name: 'NDA - HM EMR Project.pdf', type: 'pdf', x: 15, y: 72, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },
  { id: 'ca3', name: 'Service Contract 2025.pdf', type: 'pdf', x: 58, y: 34, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },
  { id: 'ca4', name: 'Residential Lease Agreement.pdf', type: 'pdf', x: 78, y: 88, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },
  { id: 'ca5', name: 'purge_agreement_proposal_new.docx', type: 'doc', x: 35, y: 15, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },
  { id: 'ca6', name: 'Vendor Agreement Draft.docx', type: 'doc', x: 68, y: 62, targetFolder: '01_Documents', targetSubfolder: 'Contracts_Agreements' },

  // === 01_DOCUMENTS - Forms_Templates (5 files) ===
  { id: 'ft1', name: 'W-4 2025.pdf', type: 'pdf', x: 8, y: 28, targetFolder: '01_Documents', targetSubfolder: 'Forms_Templates' },
  { id: 'ft2', name: 'I-9 Employment Form.pdf', type: 'pdf', x: 82, y: 45, targetFolder: '01_Documents', targetSubfolder: 'Forms_Templates' },
  { id: 'ft3', name: 'Direct Deposit Form.pdf', type: 'pdf', x: 45, y: 78, targetFolder: '01_Documents', targetSubfolder: 'Forms_Templates' },
  { id: 'ft4', name: 'Consent Forms Bundle.pdf', type: 'pdf', x: 25, y: 52, targetFolder: '01_Documents', targetSubfolder: 'Forms_Templates' },
  { id: 'ft5', name: 'Benefit Selection 2025.pdf', type: 'pdf', x: 62, y: 5, targetFolder: '01_Documents', targetSubfolder: 'Forms_Templates' },

  // === 01_DOCUMENTS - Financial_Tax (4 files) ===
  { id: 'fn1', name: 'Invoice - Jan 2025.pdf', type: 'pdf', x: 88, y: 22, targetFolder: '01_Documents', targetSubfolder: 'Financial_Tax' },
  { id: 'fn2', name: 'Payment Receipt - Provider.pdf', type: 'pdf', x: 5, y: 85, targetFolder: '01_Documents', targetSubfolder: 'Financial_Tax' },
  { id: 'fn3', name: 'Tax Docs 2024.pdf', type: 'pdf', x: 52, y: 92, targetFolder: '01_Documents', targetSubfolder: 'Financial_Tax' },
  { id: 'fn4', name: 'Credit Card Auth Form.pdf', type: 'pdf', x: 72, y: 18, targetFolder: '01_Documents', targetSubfolder: 'Financial_Tax' },

  // === 02_WORK_PROJECTS - Client_Projects (5 files) ===
  { id: 'cp1', name: 'Project Proposal v2.docx', type: 'doc', x: 18, y: 38, targetFolder: '02_Work_Projects', targetSubfolder: 'Client_Projects' },
  { id: 'cp2', name: 'Client Brief - Startup.docx', type: 'doc', x: 95, y: 68, targetFolder: '02_Work_Projects', targetSubfolder: 'Client_Projects' },
  { id: 'cp3', name: 'Scope of Work Final.docx', type: 'doc', x: 42, y: 12, targetFolder: '02_Work_Projects', targetSubfolder: 'Client_Projects' },
  { id: 'cp4', name: 'Meeting Notes - Kickoff.docx', type: 'doc', x: 75, y: 55, targetFolder: '02_Work_Projects', targetSubfolder: 'Client_Projects' },
  { id: 'cp5', name: 'Requirements Document.docx', type: 'doc', x: 28, y: 82, targetFolder: '02_Work_Projects', targetSubfolder: 'Client_Projects' },

  // === 02_WORK_PROJECTS - Invoices_Reports (4 files) ===
  { id: 'ir1', name: 'Usage Report Nov.xlsx', type: 'xlsx', x: 55, y: 48, targetFolder: '02_Work_Projects', targetSubfolder: 'Invoices_Reports' },
  { id: 'ir2', name: 'Client Invoice - Dec.pdf', type: 'pdf', x: 12, y: 8, targetFolder: '02_Work_Projects', targetSubfolder: 'Invoices_Reports' },
  { id: 'ir3', name: 'Quarterly Review.docx', type: 'doc', x: 85, y: 32, targetFolder: '02_Work_Projects', targetSubfolder: 'Invoices_Reports' },
  { id: 'ir4', name: 'Service Report Final.pdf', type: 'pdf', x: 38, y: 68, targetFolder: '02_Work_Projects', targetSubfolder: 'Invoices_Reports' },

  // === 03_DATA_FILES - CSV_Excel (12 files) ===
  { id: 'de1', name: 'Budget_2025.xlsx', type: 'xlsx', x: 65, y: 25, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de2', name: 'Accepted Cases Export.xlsx', type: 'xlsx', x: 22, y: 95, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de3', name: 'Payment Schedules.xlsx', type: 'xlsx', x: 90, y: 78, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de4', name: 'Staffing Needs 2025.xlsx', type: 'xlsx', x: 48, y: 42, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de5', name: 'Storage Pricing List.xlsx', type: 'xlsx', x: 8, y: 58, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de6', name: 'Client Demographics.xlsx', type: 'xlsx', x: 78, y: 5, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de7', name: 'Time Tracking Export.xlsx', type: 'xlsx', x: 32, y: 28, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de8', name: 'Leads from Website.xlsx', type: 'xlsx', x: 58, y: 85, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de9', name: 'Contact Addresses.xlsx', type: 'xlsx', x: 15, y: 18, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de10', name: 'API Updates Log.xlsx', type: 'xlsx', x: 92, y: 52, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de11', name: 'Import Template.xlsx', type: 'xlsx', x: 42, y: 72, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },
  { id: 'de12', name: 'Survey Results.xlsx', type: 'xlsx', x: 68, y: 38, targetFolder: '03_Data_Files', targetSubfolder: 'CSV_Excel' },

  // === 04_SOFTWARE - Installers (8 files) ===
  { id: 'sw1', name: 'Zoom.dmg', type: 'dmg', x: 5, y: 45, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw2', name: 'Slack-4.35.126.dmg', type: 'dmg', x: 82, y: 12, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw3', name: 'VSCode-darwin-arm64.dmg', type: 'dmg', x: 25, y: 62, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw4', name: 'Figma-124.dmg', type: 'dmg', x: 52, y: 8, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw5', name: 'Docker Desktop.dmg', type: 'dmg', x: 95, y: 92, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw6', name: 'Google Chrome.dmg', type: 'dmg', x: 38, y: 35, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw7', name: 'Notion-3.8.dmg', type: 'dmg', x: 72, y: 75, targetFolder: '04_Software', targetSubfolder: 'Installers' },
  { id: 'sw8', name: 'Postman-osx.dmg', type: 'dmg', x: 12, y: 88, targetFolder: '04_Software', targetSubfolder: 'Installers' },

  // === 05_MEDIA - Images (18 files - screenshots, photos) ===
  { id: 'im1', name: 'Screenshot 2025-01-15.png', type: 'screenshot', x: 85, y: 58, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im2', name: 'Screenshot 2025-01-16.png', type: 'screenshot', x: 28, y: 5, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im3', name: 'Monosnap Data Export.png', type: 'screenshot', x: 62, y: 82, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im4', name: 'Screen Shot 2025-01-18.png', type: 'screenshot', x: 18, y: 48, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im5', name: 'Screenshot 2024-11-29.png', type: 'screenshot', x: 92, y: 35, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im6', name: 'Monosnap Transcription.png', type: 'screenshot', x: 45, y: 22, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im7', name: 'homepage_post_nav.png', type: 'screenshot', x: 75, y: 95, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im8', name: 'qrcode.png', type: 'screenshot', x: 5, y: 68, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im9', name: 'pre_login_working.png', type: 'screenshot', x: 55, y: 55, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im10', name: 'IMG_7375.jpeg', type: 'screenshot', x: 35, y: 88, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im11', name: 'IMG_7406.jpeg', type: 'screenshot', x: 88, y: 15, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im12', name: 'Monosnap Railway.png', type: 'screenshot', x: 22, y: 32, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im13', name: 'IMG_6482.jpeg', type: 'screenshot', x: 68, y: 72, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im14', name: 'test_image.png', type: 'screenshot', x: 48, y: 2, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im15', name: 'image001.png', type: 'screenshot', x: 8, y: 92, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im16', name: 'WIN_20250730.jpg', type: 'screenshot', x: 78, y: 42, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im17', name: 'checkbox_click.png', type: 'screenshot', x: 32, y: 58, targetFolder: '05_Media', targetSubfolder: 'Images' },
  { id: 'im18', name: 'Screenshot 2025-01-23.png', type: 'screenshot', x: 95, y: 25, targetFolder: '05_Media', targetSubfolder: 'Images' },

  // === 06_ARCHIVES - Compressed_Files (3 files) ===
  { id: 'ar1', name: 'project_backup_2024.zip', type: 'zip', x: 58, y: 18, targetFolder: '06_Archives', targetSubfolder: 'Compressed_Files' },
  { id: 'ar2', name: 'old_assets_archive.zip', type: 'zip', x: 15, y: 42, targetFolder: '06_Archives', targetSubfolder: 'Compressed_Files' },
  { id: 'ar3', name: 'client_deliverables.zip', type: 'zip', x: 85, y: 82, targetFolder: '06_Archives', targetSubfolder: 'Compressed_Files' },

  // === 07_TEMPORARY - Downloads_Misc (2 files) ===
  { id: 'tm1', name: 'notes_random.txt', type: 'txt', x: 42, y: 65, targetFolder: '07_Temporary', targetSubfolder: 'Downloads_Misc' },
  { id: 'tm2', name: 'README_draft.txt', type: 'txt', x: 72, y: 8, targetFolder: '07_Temporary', targetSubfolder: 'Downloads_Misc' },
];

// ============================================================================
// ORGANIZATION SUMMARY CONTENT
// ============================================================================

export const ORGANIZATION_SUMMARY_CONTENT = `DESKTOP ORGANIZATION SUMMARY
Completed: ${new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}

=== FOLDER STRUCTURE ===

01_Documents/ (15 files)
  - Contracts_Agreements/ - Service agreements, NDAs, consulting contracts
  - Forms_Templates/ - Employment forms, consent forms, W-4s
  - Financial_Tax/ - Invoices, payment receipts, tax documents

02_Work_Projects/ (9 files)
  - Client_Projects/ - Project proposals, briefs, scope documents
  - Invoices_Reports/ - Client invoices, usage reports

03_Data_Files/ (12 files)
  - CSV_Excel/ - Spreadsheets, data exports, reports

04_Software/ (8 files)
  - Installers/ - Application installers (.dmg files)

05_Media/ (18 files)
  - Images/ - Screenshots, photos, diagrams

06_Archives/ (3 files)
  - Compressed_Files/ - ZIP archives, compressed packages

07_Temporary/ (2 files)
  - Downloads_Misc/ - Miscellaneous, unclassified items

=== ORGANIZATION BENEFITS ===

1. Improved Findability - Files grouped by type and purpose
2. Better Security - Sensitive documents clearly separated
3. Easier Maintenance - Clear categories for archiving
4. Professional Structure - Work separated from personal
5. Scalable System - Easy to add new files

=== NEXT STEPS ===

1. Review 07_Temporary/ for files to recategorize
2. Consider archiving older files by year
3. Set up regular maintenance schedule
4. Back up important categories
`;

// ============================================================================
// FILE ICON COMPONENT - Using actual macOS icons
// ============================================================================

export const FileIcon = ({ type, size = 'md' }: { type: FileType; size?: 'sm' | 'md' | 'lg' }) => {
  // Map file types to their icon paths
  const iconMap: Record<FileType, string> = {
    screenshot: '/images/icons/png.png',
    pdf: '/images/icons/pdf.png',
    doc: '/images/icons/word-processor.png',
    dmg: '/images/icons/dmg.png',
    txt: '/images/icons/txt.png',
    xlsx: '/images/icons/xlsx.png',
    zip: '/images/icons/folder.png', // Use folder as placeholder for zip
  };

  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-10 h-10',
    lg: 'w-12 h-12',
  };

  const containerSizes = {
    sm: 'w-4 h-5',
    md: 'w-10 h-12',
    lg: 'w-12 h-14',
  };

  return (
    <div className={`${containerSizes[size]} flex items-center justify-center`}>
      <img 
        src={iconMap[type]} 
        alt={type}
        className={`${sizeClasses[size]} object-contain`}
        style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}
      />
    </div>
  );
};

// ============================================================================
// CONTEXT COMPONENT - Files on desktop background + Finder window
// ============================================================================

export interface DesktopCleanupContextProps {
  animationStep: number;
  navigationPath?: string[];
  onNavigate?: (path: string[]) => void;
  onFileOpen?: (fileName: string) => void;
  viewingFile?: string | null;
  onCloseFile?: () => void;
}

const DesktopCleanupContext: React.FC<DesktopCleanupContextProps> = ({ 
  animationStep,
  navigationPath: navPath,
  onNavigate,
  onFileOpen,
  viewingFile,
  onCloseFile,
}) => {
  // Default navigation to Desktop root
  const navigationPath = navPath && navPath.length > 0 ? navPath : ['Desktop'];

  // Handle file open - calls parent callback (controlled from AgentTaskPanel)
  const handleFileOpen = (fileName: string) => {
    if (onFileOpen) {
      onFileOpen(fileName);
    }
  };
  // Determine which files have been moved based on step
  // Steps 0-4: All files visible (analyzing and creating folders)
  // Step 5: Documents (01_Documents) moved
  // Step 6: Work files (02_Work_Projects) moved
  // Step 7: Data files (03_Data_Files) moved
  // Step 8: Installers (04_Software) moved
  // Step 9: Media (05_Media) moved
  // Step 10: Archives (06_Archives) and Temp (07_Temporary) moved
  // Step 11: Summary created
  
  const isFileMoved = (file: DesktopFile) => {
    if (file.targetFolder === '01_Documents' && animationStep >= 5) return true;
    if (file.targetFolder === '02_Work_Projects' && animationStep >= 6) return true;
    if (file.targetFolder === '03_Data_Files' && animationStep >= 7) return true;
    if (file.targetFolder === '04_Software' && animationStep >= 8) return true;
    if (file.targetFolder === '05_Media' && animationStep >= 9) return true;
    if (file.targetFolder === '06_Archives' && animationStep >= 10) return true;
    if (file.targetFolder === '07_Temporary' && animationStep >= 10) return true;
    return false;
  };

  // Generate folder items for the Finder based on navigation level
  const getFinderContent = () => {
    const depth = navigationPath.length;
    
    if (depth === 1) {
      // At Desktop root - show main folders (only visible ones based on step)
      const visibleFolders = FOLDER_HIERARCHY.map((folder, index) => ({
        name: folder.name,
        itemCount: folder.subfolders.reduce((acc, sf) => acc + sf.fileCount, 0),
        isVisible: animationStep >= (index < 2 ? 2 : index < 4 ? 3 : 4),
        dateModified: 'Today',
        size: '--',
        kind: 'Folder',
      })).filter(f => f.isVisible);

      // Add summary file if step >= 11
      const files = animationStep >= 11 ? [{
        name: 'ORGANIZATION_SUMMARY.txt',
        dateModified: 'Today',
        size: '1 KB',
        kind: '.txt',
        isFile: true,
      }] : [];

      return { folders: visibleFolders, files };
    } else if (depth === 2) {
      // Inside a main folder - show subfolders
      const mainFolder = FOLDER_HIERARCHY.find(f => f.name === navigationPath[1]);
      if (!mainFolder) return { folders: [], files: [] };

      const subfolders = mainFolder.subfolders.map(sf => ({
        name: sf.name,
        itemCount: sf.fileCount,
        isVisible: true,
        dateModified: 'Today',
        size: '--',
        kind: 'Folder',
      }));

      return { folders: subfolders, files: [] };
    } else if (depth === 3) {
      // Inside a subfolder - show files
      const mainFolder = navigationPath[1];
      const subfolder = navigationPath[2];
      
      const filesInSubfolder = DESKTOP_FILES.filter(
        f => f.targetFolder === mainFolder && f.targetSubfolder === subfolder
      ).map(f => ({
        name: f.name,
        dateModified: 'Today',
        size: getFileSize(f.type),
        kind: getFileKind(f.type),
        isFile: true,
        fileType: f.type,
      }));

      return { folders: [], files: filesInSubfolder };
    }

    return { folders: [], files: [] };
  };

  const { folders, files } = getFinderContent();

  // Build breadcrumb title
  const title = navigationPath.join(' > ');

  return (
    <div className="relative w-full h-full min-h-[400px]">
      {/* Desktop files - positioned absolutely on the background.
          AgentTaskPanel is always rendered as a 2-column grid (the onboarding
          WebView and the website both enforce this), and the column wrapping
          this context uses overflow-visible so absolutely-positioned children
          can extend across both columns. We therefore unconditionally scale
          file.x by ~1.9x so the icons span the full panel width rather than
          being clamped to the left half. The previous innerWidth<1024 mobile
          branch incorrectly engaged inside the onboarding WKWebView (whose
          frame is narrower than 1024px) and pinned all icons to the left
          column, which is the regression we're fixing here. */}
      {DESKTOP_FILES.map((file) => {
        const moved = isFileMoved(file);
        const displayX = file.x * 1.9;
        const displayY = file.y;
        return (
          <div
            key={file.id}
            className="absolute flex flex-col items-center transition-all duration-700 ease-out"
            style={{
              left: `${displayX}%`,
              top: `${displayY}%`,
              opacity: moved ? 0 : 1,
              transform: moved ? 'scale(0.5)' : 'scale(1)',
            }}
          >
            <FileIcon type={file.type} />
            <span className="text-[8px] text-white/90 mt-0.5 truncate w-12 text-center drop-shadow-md">
              {file.name.length > 10 ? file.name.slice(0, 8) + '...' : file.name}
            </span>
          </div>
        );
      })}

      {/* Finder window - positioned in the left half */}
      <div 
        className={`absolute transition-all duration-500 ${
          animationStep >= 1 ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'
        }`}
        style={{ left: '2%', top: '4%', width: '96%', maxWidth: '400px', height: '280px' }}
      >
        <MockFinderWindow 
          title={title}
          folders={folders}
          files={files}
          currentPath={navigationPath}
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
        content={viewingFile === 'ORGANIZATION_SUMMARY.txt' ? ORGANIZATION_SUMMARY_CONTENT : ''}
      />
    </div>
  );
};

// Helper functions for file metadata
function getFileSize(type: FileType): string {
  const sizes: Record<FileType, string> = {
    screenshot: '2.4 MB',
    pdf: '156 KB',
    doc: '48 KB',
    dmg: '125 MB',
    txt: '2 KB',
    xlsx: '84 KB',
    zip: '12 MB',
  };
  return sizes[type];
}

function getFileKind(type: FileType): string {
  const kinds: Record<FileType, string> = {
    screenshot: 'PNG',
    pdf: 'PDF',
    doc: '.docx',
    dmg: '.dmg',
    txt: '.txt',
    xlsx: '.xlsx',
    zip: '.zip',
  };
  return kinds[type];
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function getPhase(time: number): AgentTaskPhase {
  if (time < TIMINGS.CAPTURE_START) return 'idle';
  if (time < TIMINGS.CAPTURE_END) return 'capture';
  if (time < TIMINGS.COMPLETE) return 'processing';
  return 'complete';
}

const COMMAND_TEXT = "I need you to help clean up my Desktop. It's a bit of a mess and I don't know how I'd want to organize everything, but can you come up with a strategy and move everything based on that?";

function getTranscript(time: number): string {
  // During capture phase, progressively reveal the speech
  if (time < TIMINGS.CAPTURE_START) return "";
  if (time >= TIMINGS.CAPTURE_END) return COMMAND_TEXT;
  
  // Calculate progress through capture phase
  const captureProgress = (time - TIMINGS.CAPTURE_START) / (TIMINGS.CAPTURE_END - TIMINGS.CAPTURE_START);
  // Return progressively more of the text
  const charsToShow = Math.floor(captureProgress * COMMAND_TEXT.length);
  return COMMAND_TEXT.substring(0, charsToShow);
}

function getCaptureProgress(time: number): number {
  if (time < TIMINGS.CAPTURE_START) return 0;
  if (time >= TIMINGS.CAPTURE_END) return 1;
  return (time - TIMINGS.CAPTURE_START) / (TIMINGS.CAPTURE_END - TIMINGS.CAPTURE_START);
}

function getStep(time: number): { index: number; label: string } {
  if (time < TIMINGS.STEP_1) return { index: 0, label: STEPS[0]?.label || '' };
  if (time < TIMINGS.STEP_2) return { index: 1, label: STEPS[1]?.label || '' };
  if (time < TIMINGS.STEP_3) return { index: 2, label: STEPS[2]?.label || '' };
  if (time < TIMINGS.STEP_4) return { index: 3, label: STEPS[3]?.label || '' };
  if (time < TIMINGS.STEP_5) return { index: 4, label: STEPS[4]?.label || '' };
  if (time < TIMINGS.STEP_6) return { index: 5, label: STEPS[5]?.label || '' };
  if (time < TIMINGS.STEP_7) return { index: 6, label: STEPS[6]?.label || '' };
  if (time < TIMINGS.STEP_8) return { index: 7, label: STEPS[7]?.label || '' };
  if (time < TIMINGS.STEP_9) return { index: 8, label: STEPS[8]?.label || '' };
  if (time < TIMINGS.STEP_10) return { index: 9, label: STEPS[9]?.label || '' };
  if (time < TIMINGS.STEP_11) return { index: 10, label: STEPS[10]?.label || '' };
  if (time < TIMINGS.STEP_12) return { index: 11, label: STEPS[11]?.label || '' };
  return { index: 12, label: STEPS[11]?.label || '' };
}

function getAnimationStep(time: number): number {
  if (time < TIMINGS.STEP_2) return 0;   // Messy
  if (time < TIMINGS.STEP_3) return 1;   // Analyzing, Finder appears
  if (time < TIMINGS.STEP_6) return 2;   // Creating folders (steps 3-5)
  if (time < TIMINGS.STEP_6 + 0.1) return 3; // Folders visible
  if (time < TIMINGS.STEP_6 + 0.1) return 4; // Extra step
  if (time < TIMINGS.STEP_7) return 5;   // Documents moved
  if (time < TIMINGS.STEP_8) return 6;   // Work files moved
  if (time < TIMINGS.STEP_9) return 7;   // Data files moved
  if (time < TIMINGS.STEP_10) return 8;  // Installers moved
  if (time < TIMINGS.STEP_11) return 9;  // Media moved
  if (time < TIMINGS.STEP_12) return 10; // Archives moved
  if (time >= TIMINGS.COMPLETE) return 11; // Summary created, done
  return 10;
}

// ============================================================================
// USE CASE EXPORT
// ============================================================================

export const desktopCleanupUseCase: AgentTaskUseCase = {
  id: 'desktop-cleanup',
  label: 'Desktop Cleanup',
  icon: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  ),
  
  // Timing
  duration: DURATION,
  getPhase,
  
  // Capture
  getTranscript,
  getCaptureProgress,
  
  // Processing
  getStep,
  totalSteps: STEPS.length,
  steps: STEPS,
  
  // Complete - more detailed
  commandText: COMMAND_TEXT,
  resultSummary: "Successfully organized your desktop! Created a 7-category folder structure with 10 subfolders, moved 67 files, and generated an organization summary.",
  completedSteps: COMPLETED_STEPS,
  structuredFiles: STRUCTURED_FILES,
  
  // Context
  ContextComponent: DesktopCleanupContext,
  getAnimationStep,
};

export default DesktopCleanupContext;
