import { requestResize } from '../services/bridge';

/** How much taller the window gets when the follow-up box opens again at the end of a run, so the transcript keeps the room it had while the box was folded. */
export const FOLLOW_UP_UNFOLD_GROWTH_PX = 120;

/** The same ceiling the content-fit sizing uses. */
const MAX_WINDOW_HEIGHT_PX = 900;

/** Asks the window to grow by the height the box takes. A window already near the ceiling grows only as far as the ceiling allows, and one that cannot grow asks for nothing. */
export function growWindowForUnfoldedFollowUp(
  currentWidth: number = window.innerWidth,
  currentHeight: number = window.innerHeight,
): boolean {
  const targetHeight = Math.min(currentHeight + FOLLOW_UP_UNFOLD_GROWTH_PX, Math.max(currentHeight, MAX_WINDOW_HEIGHT_PX));
  if (targetHeight - currentHeight < 4) return false;
  requestResize(currentWidth, targetHeight, 'content');
  return true;
}
