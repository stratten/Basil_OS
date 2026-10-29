import { useEffect, useLayoutEffect, useRef } from 'react';
import type { ArtifactPreviewTransport, InlineNativePreviewFrame } from './transport/artifactPreviewTransport';

export interface NativeArtifactPreviewSlotProps {
  requestId?: string;
  enabled: boolean;
  transport: ArtifactPreviewTransport;
}

function isFinitePositive(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function isVisibleFrame(frame: InlineNativePreviewFrame): boolean {
  return frame.left < frame.viewportWidth
    && frame.top < frame.viewportHeight
    && frame.left + frame.width > 0
    && frame.top + frame.height > 0;
}

function frameFromElement(element: HTMLDivElement): InlineNativePreviewFrame | undefined {
  const rect = element.getBoundingClientRect();
  const frame: InlineNativePreviewFrame = {
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
  };
  const hasFiniteCoordinates = Number.isFinite(frame.left) && Number.isFinite(frame.top);
  const hasPositiveDimensions = isFinitePositive(frame.width)
    && isFinitePositive(frame.height)
    && isFinitePositive(frame.viewportWidth)
    && isFinitePositive(frame.viewportHeight);
  return hasFiniteCoordinates && hasPositiveDimensions ? frame : undefined;
}

function frameKey(requestId: string, frame: InlineNativePreviewFrame): string {
  return `${requestId}:${frame.left}:${frame.top}:${frame.width}:${frame.height}:${frame.viewportWidth}:${frame.viewportHeight}`;
}

export function useNativeArtifactPreviewSlot({
  requestId,
  enabled,
  transport,
}: NativeArtifactPreviewSlotProps) {
  const slotRef = useRef<HTMLDivElement>(null);
  const lastReportedKey = useRef<string>();
  const activeRequestId = useRef<string>();

  useLayoutEffect(() => {
    const previousRequestId = activeRequestId.current;
    if (!enabled || !requestId) {
      if (previousRequestId) transport.clearInlineNativePreview(previousRequestId);
      activeRequestId.current = undefined;
      lastReportedKey.current = undefined;
      return;
    }

    if (previousRequestId && previousRequestId !== requestId) {
      transport.clearInlineNativePreview(previousRequestId);
      lastReportedKey.current = undefined;
    }
    activeRequestId.current = requestId;

    let animationFrame = 0;
    const reportFrame = () => {
      animationFrame = 0;
      if (activeRequestId.current !== requestId) return;
      const element = slotRef.current;
      if (!element) return;

      const frame = frameFromElement(element);
      if (!frame || !isVisibleFrame(frame)) {
        const hiddenKey = `${requestId}:hidden`;
        if (lastReportedKey.current !== hiddenKey) {
          transport.hideInlineNativePreview(requestId);
          lastReportedKey.current = hiddenKey;
        }
        return;
      }

      const nextKey = frameKey(requestId, frame);
      if (lastReportedKey.current === nextKey) return;
      transport.setInlineNativePreviewFrame(requestId, frame);
      lastReportedKey.current = nextKey;
    };

    const scheduleFrameReport = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(reportFrame);
    };

    const resizeObserver = new ResizeObserver(scheduleFrameReport);
    if (slotRef.current) resizeObserver.observe(slotRef.current);
    window.addEventListener('resize', scheduleFrameReport);
    document.addEventListener('scroll', scheduleFrameReport, true);
    reportFrame();

    return () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      window.removeEventListener('resize', scheduleFrameReport);
      document.removeEventListener('scroll', scheduleFrameReport, true);
      if (activeRequestId.current === requestId) {
        transport.clearInlineNativePreview(requestId);
        activeRequestId.current = undefined;
        lastReportedKey.current = undefined;
      }
    };
  }, [enabled, requestId, transport]);

  useEffect(() => () => {
    const currentRequestId = activeRequestId.current;
    if (currentRequestId) transport.clearInlineNativePreview(currentRequestId);
  }, []);

  return slotRef;
}
