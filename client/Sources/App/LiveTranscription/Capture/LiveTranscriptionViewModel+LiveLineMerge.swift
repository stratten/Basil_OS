import Foundation

// MARK: - Live Line Merge
//
// Single shared path for folding freshly transcribed live lines into the
// per-source transcript buffers. The microphone and system-audio websocket
// handlers previously carried near-identical copies of this logic; centralizing
// it removes that duplication and gives resume one place to stamp the timeline
// offset so new lines order after retained prior-part lines.
extension LiveTranscriptionViewModel {

    /// Minimum word count before sentence-ending punctuation closes a live line.
    /// The single tuning knob for live line granularity: lower splits more
    /// aggressively (including short backchannels), higher groups more.
    static let liveSentenceBreakMinWords = 5

    /// Append a batch of freshly transcribed live lines to the given source's
    /// transcript: start a new line or extend the in-progress one, close the
    /// other source's in-progress line on a source switch, refresh the shared
    /// line-break timer, and rebuild the combined view.
    ///
    /// During a resumed recording the backend streams part-relative timestamps,
    /// so each newly started line is stamped with
    /// `timelineStartSeconds = parse(start) + resumeTimelineOffsetSeconds`, which
    /// keeps it ordered after the retained prior-part lines. Fresh recordings
    /// keep the historical behavior (no canonical seconds stamped here).
    @MainActor
    func appendLiveLines(_ lines: [TranscriptionLine], to source: AudioSource) {
        guard !lines.isEmpty else { return }

        // Activity from any source resets the shared line-break timer.
        globalLineBreakTimer?.cancel()

        // NOTE: we intentionally do NOT close the other source's in-progress line
        // here. The two sources route to independent per-source arrays, so closing
        // the sibling on every inbound batch (the backend pushes 1-3 token deltas
        // at min_chunk_size=0.1s) shredded concurrent speech into per-second
        // bubbles. Lines now close only on real signals: the backend `lineComplete`
        // flag (set after >2s of silence) and the 3s global line-break timer.
        for line in lines {
            appendOneLiveLine(line, to: source)
        }

        startGlobalLineBreakTimer()
        updateCombinedTranscript()
    }

    /// Append a single live line into the target source array: extend the
    /// current in-progress line, or start a new one.
    private func appendOneLiveLine(_ line: TranscriptionLine, to source: AudioSource) {
        switch source {
        case .microphone:
            if !microphoneTranscript.isEmpty && !microphoneTranscript.last!.lineComplete {
                var current = microphoneTranscript.removeLast()
                current.text = normalizeWhitespace(current.text + line.text)
                current.lineComplete = line.lineComplete || sentenceBreaks(current.text)
                current.source = .microphone
                microphoneTranscript.append(current)
            } else {
                var started = startedLine(from: line, source: .microphone)
                started.lineComplete = started.lineComplete || sentenceBreaks(started.text)
                microphoneTranscript.append(started)
            }
        case .systemAudio:
            if !systemAudioTranscript.isEmpty && !systemAudioTranscript.last!.lineComplete {
                var current = systemAudioTranscript.removeLast()
                current.text = normalizeWhitespace(current.text + line.text)
                current.lineComplete = line.lineComplete || sentenceBreaks(current.text)
                current.source = .systemAudio
                systemAudioTranscript.append(current)
            } else {
                var started = startedLine(from: line, source: .systemAudio)
                started.lineComplete = started.lineComplete || sentenceBreaks(started.text)
                systemAudioTranscript.append(started)
            }
        }
    }

    /// Whether the accumulated line text reaches a sentence boundary at the
    /// configured min-word threshold. When true the line is closed so the next
    /// inbound batch opens a fresh, freshly-stamped line, which divides a long
    /// monologue into sentence-level bubbles and lets the other source interleave.
    private func sentenceBreaks(_ text: String) -> Bool {
        TranscriptSentenceBreak.endsAtSentenceBoundary(text, minWords: Self.liveSentenceBreakMinWords)
    }

    /// Build a new line from an incoming live line, anchoring its on-screen
    /// timestamp to the backend's own per-source stream position rather than
    /// wall-clock receipt time.
    ///
    /// The backend's `timeline_start_seconds` is a continuous, sample-accurate
    /// position in that source's own audio stream (silence gaps are now
    /// measured from real sample counts, not wall-clock reads - see
    /// `AudioProcessor._timeline_end_for_sample` - so it no longer drifts ahead
    /// of true elapsed time under processing load). The backend has already
    /// anchored each source's stream-relative token positions to the native
    /// capture clock before emitting them. The renderer only applies the
    /// logical resumed-part offset, never a receipt-time correction.
    private func startedLine(from line: TranscriptionLine, source: AudioSource) -> TranscriptionLine {
        guard let backendPosition = line.timelineStartSeconds else {
            // The backend did not send a stream position for this line: preserve
            // its existing values and just tag the source.
            var newLine = line
            newLine.source = source
            return newLine
        }

        let elapsed = max(0, backendPosition + resumeTimelineOffsetSeconds)
        let backendEnd = line.timelineEndSeconds ?? backendPosition
        let elapsedEnd = max(elapsed, backendEnd + resumeTimelineOffsetSeconds)
        return TranscriptionLine(
            id: line.id,
            text: line.text,
            speakerID: line.speakerID,
            isInterim: line.isInterim,
            start: line.start,
            end: line.end,
            diff: line.diff,
            timelineStartSeconds: elapsed,
            timelineEndSeconds: elapsedEnd,
            source: source,
            lineComplete: line.lineComplete
        )
    }

}
