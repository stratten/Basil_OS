import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { formatClockSeconds } from '@shared/formatClockSeconds'

const KEYBOARD_STEP_SECONDS = 5

export interface TranscriptionPlaybackProgress {
  positionSeconds: number
  durationSeconds: number
}

interface TranscriptionPlaybackBarProps {
  /** Null while native is still fetching the audio, before the first progress event. */
  progress: TranscriptionPlaybackProgress | null
  onSeek: (seconds: number) => void
}

function clampSeconds(seconds: number, durationSeconds: number): number {
  if (!Number.isFinite(seconds)) return 0
  return Math.min(Math.max(seconds, 0), durationSeconds)
}

/** Playback position for one transcription: a seekable bar with elapsed and total time. */
export function TranscriptionPlaybackBar({ progress, onSeek }: TranscriptionPlaybackBarProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [dragSeconds, setDragSeconds] = useState<number | null>(null)

  if (!progress || !(progress.durationSeconds > 0)) {
    return (
      <div className="transcription-playback" role="status">
        <div className="transcription-playback-track transcription-playback-track-loading" aria-hidden="true">
          <div className="transcription-playback-fill transcription-playback-fill-loading" />
        </div>
        <span className="transcription-playback-time">Loading audio…</span>
      </div>
    )
  }

  const { durationSeconds } = progress
  const shownSeconds = clampSeconds(dragSeconds ?? progress.positionSeconds, durationSeconds)
  const percent = (shownSeconds / durationSeconds) * 100
  const elapsedText = formatClockSeconds(shownSeconds)
  const totalText = formatClockSeconds(durationSeconds)

  function secondsFromPointer(event: PointerEvent<HTMLDivElement>): number {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect || rect.width <= 0) return 0
    const fraction = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
    return fraction * durationSeconds
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setDragSeconds(secondsFromPointer(event))
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (dragSeconds === null) return
    setDragSeconds(secondsFromPointer(event))
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    if (dragSeconds === null) return
    const target = secondsFromPointer(event)
    setDragSeconds(null)
    onSeek(target)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    let target: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') target = shownSeconds + KEYBOARD_STEP_SECONDS
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') target = shownSeconds - KEYBOARD_STEP_SECONDS
    else if (event.key === 'Home') target = 0
    else if (event.key === 'End') target = durationSeconds
    if (target === null) return
    event.preventDefault()
    onSeek(clampSeconds(target, durationSeconds))
  }

  return (
    <div className="transcription-playback">
      <div
        ref={trackRef}
        className={`transcription-playback-track${dragSeconds !== null ? ' transcription-playback-track-dragging' : ''}`}
        role="slider"
        tabIndex={0}
        aria-label="Playback position"
        aria-valuemin={0}
        aria-valuemax={Math.floor(durationSeconds)}
        aria-valuenow={Math.floor(shownSeconds)}
        aria-valuetext={`${elapsedText} of ${totalText}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => setDragSeconds(null)}
        onKeyDown={handleKeyDown}
      >
        <div className="transcription-playback-fill" style={{ width: `${percent}%` }} />
        <div className="transcription-playback-thumb" style={{ left: `${percent}%` }} />
      </div>
      <span className="transcription-playback-time">
        <span className="transcription-playback-elapsed">{elapsedText}</span>
        <span aria-hidden="true"> / </span>
        <span className="transcription-playback-total">{totalText}</span>
      </span>
    </div>
  )
}
