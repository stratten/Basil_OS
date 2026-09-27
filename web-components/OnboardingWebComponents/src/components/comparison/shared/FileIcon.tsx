"use client";

import React from 'react';

export type FileType = 'screenshot' | 'pdf' | 'doc' | 'dmg' | 'txt' | 'xlsx' | 'zip' | 'folder';

interface FileIconProps {
  type: FileType;
  size?: 'sm' | 'md' | 'lg';
}

const FileIcon: React.FC<FileIconProps> = ({ type, size = 'md' }) => {
  // Map file types to their icon paths
  const iconMap: Record<FileType, string> = {
    screenshot: '/images/icons/png.png',
    pdf: '/images/icons/pdf.png',
    doc: '/images/icons/word-processor.png',
    dmg: '/images/icons/dmg.png',
    txt: '/images/icons/txt.png',
    xlsx: '/images/icons/xlsx.png',
    zip: '/images/icons/folder.png',
    folder: '/images/icons/folder.png',
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

export default FileIcon;
