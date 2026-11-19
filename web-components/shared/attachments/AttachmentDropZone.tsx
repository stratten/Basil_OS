import { useState, type DragEvent, type HTMLAttributes, type Ref } from 'react';
import './attachment-area.css';
import { UploadGlyph } from './attachmentGlyphs';
import { DROP_OVERLAY_TEXT } from './attachmentPaths';

export interface AttachmentDropZoneProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onDragEnter' | 'onDragOver' | 'onDragLeave' | 'onDrop'> {
  /** When true the zone swallows drags (so WebKit never navigates to the file) but shows no highlight and never arms. */
  disabled?: boolean;
  /** Called on every drag-enter and drag-over while enabled, so arming windows can refresh their routing target or expiry timer. */
  onArm?: () => void;
  /** Called when the drag leaves the zone, and also when the drop lands unless `disarmOnDrop` is false. */
  onDisarm?: () => void;
  /** Default true. Companion sets false: its arm window is JS-side and the native paths callback can arrive after the DOM drop event, so only leaving or the arm expiry may disarm it. */
  disarmOnDrop?: boolean;
  overlayText?: string;
  zoneRef?: Ref<HTMLDivElement>;
}

/** Wraps one region with the local drag highlight and the standard overlay. It never reads dropped paths: WKWebView does not expose `File.path`, so the native side delivers them through the window's own callback. */
export default function AttachmentDropZone({ children, className, disabled = false, onArm, onDisarm, disarmOnDrop = true, overlayText = DROP_OVERLAY_TEXT, zoneRef, ...rest }: AttachmentDropZoneProps) {
  const [active, setActive] = useState(false);

  const handleHover = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (disabled) return;
    onArm?.();
    setActive(true);
  };

  const handleLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setActive(false);
    onDisarm?.();
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    // Stops WebKit from navigating to the dropped file; the paths themselves arrive through the native callback.
    event.preventDefault();
    event.stopPropagation();
    setActive(false);
    if (disarmOnDrop) onDisarm?.();
  };

  const classes = ['attachment-drop-zone', className, active ? 'is-drag-over' : ''].filter(Boolean).join(' ');

  return (
    <div {...rest} ref={zoneRef} className={classes} onDragEnter={handleHover} onDragOver={handleHover} onDragLeave={handleLeave} onDrop={handleDrop}>
      {children}
      {active && (
        <div className="attachment-drop-overlay" aria-hidden="true">
          <UploadGlyph />
          <span>{overlayText}</span>
        </div>
      )}
    </div>
  );
}
