"use client";

import { useState, useEffect } from 'react';

interface SimulatedMenuBarProps {
  /** Whether recording is active (shows mic indicator) */
  isRecording?: boolean;
}

/**
 * Simulated macOS menu bar for demo components.
 * Shows Apple menu, app menu, system icons, and recording indicator.
 * Designed to sit edge-to-edge at the top of the demo viewport.
 */
const SimulatedMenuBar = ({ isRecording = false }: SimulatedMenuBarProps) => {
  const [currentTime, setCurrentTime] = useState<string>('');

  // Update time every minute
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const formatter = new Intl.DateTimeFormat('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
      });
      setCurrentTime(formatter.format(now));
    };

    updateTime();
    const interval = setInterval(updateTime, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-center justify-between h-6 px-2 bg-black/50 backdrop-blur-md shrink-0">
      {/* Left side: Apple menu + App menu */}
      <div className="flex items-center gap-4">
        {/* Apple logo */}
        <svg viewBox="0 0 24 24" className="w-4 h-4 text-white/90" fill="currentColor">
          <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/>
        </svg>
        
        {/* App name (Basil) - bold like active app */}
        <span className="text-[13px] text-white/95 font-semibold">Basil</span>
        
        {/* Standard menu items */}
        <div className="flex items-center gap-4">
          <span className="text-[13px] text-white/90">File</span>
          <span className="text-[13px] text-white/90">Edit</span>
          <span className="text-[13px] text-white/90">View</span>
          <span className="text-[13px] text-white/90">Window</span>
          <span className="text-[13px] text-white/90">Help</span>
        </div>
      </div>

      {/* Right side: Status icons */}
      <div className="flex items-center gap-3">
        {/* Basil status icon - actual app icon files */}
        <img 
          src={isRecording ? '/images/icons/BasilMenuIcon_Recording.png' : '/images/icons/BasilMenuIcon_Idle.png'}
          alt="Basil"
          className="w-[18px] h-[18px] object-contain"
        />

        {/* macOS mic recording indicator - orange background when recording */}
        <div 
          className={`flex items-center justify-center w-5 h-5 rounded transition-all duration-200 ${
            isRecording ? 'bg-orange-500' : 'bg-transparent'
          }`}
        >
          <svg 
            viewBox="0 0 24 24" 
            className={`w-3 h-3 transition-colors duration-200 ${
              isRecording ? 'text-white' : 'text-white/90'
            }`}
            fill="currentColor"
          >
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
          </svg>
        </div>

        {/* Divider */}
        <div className="w-px h-3.5 bg-white/20" />

        {/* Battery */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-white/90 font-medium">100%</span>
          <div className="relative">
            <div className="w-[18px] h-[9px] border border-white/90 rounded-sm">
              <div className="absolute inset-[1px] bg-green-400 rounded-[1px]" />
            </div>
            <div className="absolute -right-[2px] top-1/2 -translate-y-1/2 w-[2px] h-1 bg-white/90 rounded-r-sm" />
          </div>
        </div>

        {/* Bluetooth */}
        <svg viewBox="0 0 24 24" className="w-3 h-3 text-white/90" fill="currentColor">
          <path d="M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z"/>
        </svg>

        {/* WiFi */}
        <svg viewBox="0 0 24 24" className="w-3 h-3 text-white/90" fill="currentColor">
          <path d="M1 9l2 2c4.97-4.97 13.03-4.97 18 0l2-2C16.93 2.93 7.08 2.93 1 9zm8 8l3 3 3-3c-1.65-1.66-4.34-1.66-6 0zm-4-4l2 2c2.76-2.76 7.24-2.76 10 0l2-2C15.14 9.14 8.87 9.14 5 13z"/>
        </svg>

        {/* Date and Time */}
        <span className="text-[11px] text-white/95 font-medium tracking-tight">
          {currentTime}
        </span>
      </div>
    </div>
  );
};

export default SimulatedMenuBar;
