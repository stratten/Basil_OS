import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  src: string
  alt: string
  caption?: string
  onClose: () => void
}

/** Shows one setup reference image at the largest size the window allows. Escape, the close button, or a click on the dark backdrop closes it, and focus returns to whatever opened it. */
export function SetupImageLightbox({ src, alt, caption, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      previouslyFocused?.focus?.()
    }
  }, [])

  return createPortal(
    <div
      className="setup-image-lightbox-backdrop"
      data-testid="setup-image-lightbox"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className="setup-image-lightbox"
        role="dialog"
        aria-modal="true"
        aria-label={alt}
        tabIndex={-1}
      >
        <button type="button" className="setup-image-lightbox-close" aria-label="Close image" onClick={onClose}>
          ×
        </button>
        <img className="setup-image-lightbox-image" src={src} alt={alt} />
        {caption ? <p className="setup-image-lightbox-caption">{caption}</p> : null}
      </div>
    </div>,
    document.body,
  )
}
