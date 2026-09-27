"use client";

import React from 'react';

export interface FolderItem {
  name: string;
  itemCount: number;
  isVisible: boolean;
  dateModified?: string;
  size?: string;
  kind?: string;
}

export interface FileItem {
  name: string;
  dateModified?: string;
  size?: string;
  kind?: string;
  isFile: boolean;
  fileType?: string;
}

interface MockFinderWindowProps {
  /** Title shown in window header (or use currentPath for breadcrumb) */
  title?: string;
  /** Folders to display in list view */
  folders?: FolderItem[];
  /** Files to display (when navigated to subfolder level) */
  files?: FileItem[];
  /** Current navigation path for breadcrumb and back button logic */
  currentPath?: string[];
  /** Navigation callback - receives new path array */
  onNavigate?: (path: string[]) => void;
  /** File open callback - for double-clicking files */
  onFileOpen?: (fileName: string) => void;
  /** Close window callback - clicking the red button */
  onClose?: () => void;
  /** Optional className */
  className?: string;
}

/**
 * MockFinderWindow - A macOS Finder window in list view.
 * Supports 3-level navigation: Desktop → Main Folder → Subfolder
 */
const MockFinderWindow = ({
  title,
  folders = [],
  files = [],
  currentPath = ['Desktop'],
  onNavigate,
  onFileOpen,
  onClose,
  className = "",
}: MockFinderWindowProps) => {
  const depth = currentPath.length;
  const canGoBack = depth > 1;
  
  // Build display title from path if not provided
  const displayTitle = title || currentPath.join(' > ');

  // Handle back navigation
  const handleBack = () => {
    if (canGoBack && onNavigate) {
      onNavigate(currentPath.slice(0, -1));
    }
  };

  // Handle folder double-click
  const handleFolderDoubleClick = (folderName: string) => {
    if (onNavigate) {
      onNavigate([...currentPath, folderName]);
    }
  };

  // Handle file double-click
  const handleFileDoubleClick = (fileName: string) => {
    if (onFileOpen) {
      onFileOpen(fileName);
    }
  };

  const visibleFolders = folders.filter(f => f.isVisible);

  return (
    <div className={`bg-[#1e1e1e] rounded-lg overflow-hidden shadow-xl h-full flex flex-col ${className}`}>
      {/* Window title bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#2d2d2d] border-b border-[#3d3d3d]">
        <div className="flex gap-1.5">
          <button 
            className="w-3 h-3 rounded-full bg-[#ff5f57] hover:bg-[#ff4136] transition-colors cursor-pointer"
            onClick={onClose}
            title="Close"
          />
          <div className="w-3 h-3 rounded-full bg-[#febc2e]" />
          <div className="w-3 h-3 rounded-full bg-[#28c840]" />
        </div>
        {/* Navigation buttons */}
        <div className="flex gap-1 ml-2">
          <button
            onClick={handleBack}
            disabled={!canGoBack}
            className={`w-5 h-5 rounded flex items-center justify-center transition-colors ${
              canGoBack 
                ? 'bg-[#3d3d3d] hover:bg-[#4a4a4a] cursor-pointer' 
                : 'bg-[#2a2a2a] cursor-not-allowed'
            }`}
          >
            <svg 
              className={`w-3 h-3 ${canGoBack ? 'text-gray-300' : 'text-gray-600'}`} 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="w-5 h-5 rounded bg-[#2a2a2a] flex items-center justify-center">
            <svg className="w-3 h-3 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </div>
        {/* Title / Breadcrumb */}
        <div className="flex-1 text-center">
          <span className="text-xs text-gray-300 font-medium">{displayTitle}</span>
        </div>
        {/* View buttons placeholder */}
        <div className="flex gap-1">
          <div className="w-5 h-5 rounded bg-[#3d3d3d]" />
          <div className="w-5 h-5 rounded bg-[#4a4a4a]" />
        </div>
      </div>

      {/* List view content */}
      <div className="flex-1 bg-[#1e1e1e] flex flex-col overflow-hidden">
        {/* Column headers */}
        <div className="flex items-center px-3 py-1.5 border-b border-[#3d3d3d] bg-[#252525] flex-shrink-0">
          <div className="flex-1 min-w-0">
            <span className="text-[10px] text-gray-400 font-medium">Name</span>
          </div>
          <div className="w-24 text-right flex-shrink-0">
            <span className="text-[10px] text-gray-400 font-medium">Date Modified</span>
          </div>
          <div className="w-14 text-right flex-shrink-0">
            <span className="text-[10px] text-gray-400 font-medium">Size</span>
          </div>
          <div className="w-14 text-right flex-shrink-0">
            <span className="text-[10px] text-gray-400 font-medium">Kind</span>
          </div>
        </div>

        {/* Content list */}
        <div className="py-1 flex-1 overflow-y-auto">
          {/* Folders */}
          {visibleFolders.map((folder, index) => (
            <div
              key={folder.name}
              onDoubleClick={() => handleFolderDoubleClick(folder.name)}
              className={`flex items-center px-3 py-1 transition-all duration-500 hover:bg-[#2a2a2a] cursor-pointer select-none ${
                folder.isVisible 
                  ? 'opacity-100 translate-y-0' 
                  : 'opacity-0 -translate-y-2 h-0 py-0 overflow-hidden'
              }`}
              style={{ transitionDelay: folder.isVisible ? `${index * 100}ms` : '0ms' }}
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <svg className="w-5 h-5 text-blue-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                </svg>
                <span className="text-xs text-gray-200 truncate">{folder.name}</span>
              </div>
              <div className="w-24 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{folder.dateModified || 'Today'}</span>
              </div>
              <div className="w-14 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{folder.size || '--'}</span>
              </div>
              <div className="w-14 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{folder.kind || 'Folder'}</span>
              </div>
            </div>
          ))}

          {/* Files */}
          {files.map((file, index) => (
            <div
              key={file.name}
              onDoubleClick={() => handleFileDoubleClick(file.name)}
              className="flex items-center px-3 py-1 hover:bg-[#2a2a2a] cursor-pointer select-none transition-all duration-300"
              style={{ transitionDelay: `${index * 50}ms` }}
            >
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <FileIconSmall type={file.fileType || getFileTypeFromName(file.name)} />
                <span className="text-xs text-gray-200 truncate">{file.name}</span>
              </div>
              <div className="w-24 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{file.dateModified || 'Today'}</span>
              </div>
              <div className="w-14 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{file.size || '--'}</span>
              </div>
              <div className="w-14 text-right flex-shrink-0">
                <span className="text-[10px] text-gray-500">{file.kind || 'Document'}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Empty state */}
        {visibleFolders.length === 0 && files.length === 0 && (
          <div className="flex items-center justify-center flex-1 text-gray-500 text-xs">
            No items
          </div>
        )}
      </div>
    </div>
  );
};

// Helper component for small file icons in list view
const FileIconSmall = ({ type }: { type: string }) => {
  const iconMap: Record<string, string> = {
    screenshot: '/images/icons/png.png',
    pdf: '/images/icons/pdf.png',
    doc: '/images/icons/word-processor.png',
    dmg: '/images/icons/dmg.png',
    txt: '/images/icons/txt.png',
    xlsx: '/images/icons/xlsx.png',
    zip: '/images/icons/folder.png',
    folder: '/images/icons/folder.png',
  };

  const src = iconMap[type] || '/images/icons/txt.png';

  return (
    <img 
      src={src} 
      alt={type}
      className="w-4 h-4 object-contain flex-shrink-0"
    />
  );
};

// Helper to guess file type from name
function getFileTypeFromName(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  const extMap: Record<string, string> = {
    png: 'screenshot',
    jpg: 'screenshot',
    jpeg: 'screenshot',
    pdf: 'pdf',
    doc: 'doc',
    docx: 'doc',
    dmg: 'dmg',
    txt: 'txt',
    xlsx: 'xlsx',
    xls: 'xlsx',
    csv: 'xlsx',
    zip: 'zip',
  };
  return extMap[ext] || 'txt';
}

export default MockFinderWindow;
