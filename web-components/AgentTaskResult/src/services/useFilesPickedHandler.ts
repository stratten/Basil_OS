import { createContext, useContext, useEffect, useRef } from 'react';
import { registerFilesPickedHandler } from './bridge';

/** False inside the copy of a surface that is fading out. That copy is mounted fresh after the incoming surface, so letting it register would take the drop channel from the surface the user is looking at. */
export const SurfaceActivityContext = createContext(true);

/** Receives files that were picked or dropped on the window while this component's surface is the one on screen. The channel has a single owner, so only the visible surface may register. */
export function useFilesPickedHandler(handler: (paths: string[]) => void): void {
  const surfaceIsActive = useContext(SurfaceActivityContext);
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  });
  useEffect(() => {
    if (!surfaceIsActive) return undefined;
    return registerFilesPickedHandler((paths) => handlerRef.current(paths));
  }, [surfaceIsActive]);
}
