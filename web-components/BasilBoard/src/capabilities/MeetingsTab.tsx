import { useEffect, useState } from 'react';
import type { BoardMeetingsAvailability } from '../contracts';
import {
  activateBoardMeetingsSurface,
  deactivateBoardMeetingsSurface,
  registerBoardMeetingsAvailabilityHandler,
} from '../services/bridge';

export default function MeetingsTab() {
  const [availability, setAvailability] = useState<BoardMeetingsAvailability>('embedded');

  useEffect(() => {
    const unregister = registerBoardMeetingsAvailabilityHandler((payload) => {
      setAvailability(payload.availability);
    });
    activateBoardMeetingsSurface();
    return () => {
      deactivateBoardMeetingsSurface();
      unregister();
    };
  }, []);

  if (availability === 'separate_window') {
    return (
      <div className="home-unavailable-state basil-board-detached-placeholder" role="status">
        <p>Notetaker is open in a separate window.</p>
        <p>Close that window to view Notetaker here.</p>
      </div>
    );
  }

  return <div className="meetings-embedded-spacer" aria-label="Notetaker" />;
}
