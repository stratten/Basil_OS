import { useEffect, useState } from 'react';
import type { BoardAgentTasksAvailability } from '../contracts';
import {
  activateBoardAgentTasksSurface,
  deactivateBoardAgentTasksSurface,
  registerBoardAgentTasksAvailabilityHandler,
} from '../services/bridge';

export default function AgentTasksHostPlaceholder() {
  const [availability, setAvailability] = useState<BoardAgentTasksAvailability>('embedded');

  useEffect(() => {
    const unregister = registerBoardAgentTasksAvailabilityHandler((payload) => {
      setAvailability(payload.availability);
    });
    activateBoardAgentTasksSurface();
    return () => {
      deactivateBoardAgentTasksSurface();
      unregister();
    };
  }, []);

  if (availability === 'separate_window') {
    return (
      <div className="home-unavailable-state basil-board-detached-placeholder" role="status">
        <p>Agents is open in a separate window.</p>
        <p>Close that window to view Agents here.</p>
      </div>
    );
  }

  return (
    <div className="agent-tasks-embedded-spacer" aria-label="Agents" />
  );
}
