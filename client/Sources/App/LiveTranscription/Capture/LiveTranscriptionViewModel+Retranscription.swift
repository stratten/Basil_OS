import Foundation

/// Mid-recording incremental re-transcription (threshold cadence).
///
/// While recording, a cadence loop periodically asks the backend to re-transcribe
/// the newly-elapsed window `[lastCheckpoint, boundary)` with the higher-quality
/// post-processing model and splices the result into the live transcript in
/// place. This upgrades earlier audio without waiting for the full on-stop pass.
extension LiveTranscriptionViewModel {

    /// Begin the cadence loop for the current recording when enabled. Individual
    /// ticks defer until an execution model is available.
    func startRetranscribeCadence() {
        guard PostProcessingAutomation.shouldArmMidRecordingCadence(
            enabled: sessionAutoRetranscribeDuringRecording
        ) else { return }

        retranscribeCadenceTask?.cancel()
        lastRetranscribeCheckpointByMeeting.removeAll()
        retranscribeWindowInFlight = false

        let interval = Double(max(1, sessionRetranscribeWindowSeconds))
        // Poll well under the cadence interval so a completed window is detected
        // promptly; the boundary math (nextCheckpointEnd) gates the actual work.
        let pollSeconds = max(5.0, min(30.0, interval / 4.0))

        #if DEBUG
        DevLogger.shared.info("Starting mid-recording re-transcription cadence: interval=\(interval)s model=\(postProcessingModel)", context: "LiveTranscriptionViewModel")
        #endif

        retranscribeCadenceTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(pollSeconds * 1_000_000_000))
                guard let self = self, !Task.isCancelled, self.isRecording else { return }
                await self.runRetranscribeCadenceTickIfDue()
            }
        }
    }

    /// Cancel the cadence loop. Leaves the per-meeting checkpoints in place so the
    /// on-stop tail pass knows where cadence left off.
    func stopRetranscribeCadence() {
        retranscribeCadenceTask?.cancel()
        retranscribeCadenceTask = nil
        retranscribeWindowInFlight = false
        windowRetranscriptionStatus = nil
    }

    /// Run one cadence tick: for each active track, if a full interval of new
    /// audio has elapsed since its last checkpoint, re-transcribe that window and
    /// advance the checkpoint. Windows run one at a time so a slow large-model
    /// pass never overlaps the next tick or doubles up across tracks.
    func runRetranscribeCadenceTickIfDue() async {
        guard !retranscribeWindowInFlight else { return }
        guard let startTime = recordingStartTime else { return }
        guard !postProcessingModel.isEmpty else {
            #if DEBUG
            DevLogger.shared.info("Deferring mid-recording re-transcription until an execution model is available", context: "LiveTranscriptionViewModel")
            #endif
            return
        }

        let elapsed = Date().timeIntervalSince(startTime)
        let interval = Double(max(1, sessionRetranscribeWindowSeconds))

        let tracks: [(meetingId: String, source: AudioSource)] = [
            (microphoneMeetingId, AudioSource.microphone),
            (systemAudioMeetingId, AudioSource.systemAudio)
        ].compactMap { id, source in id.map { (meetingId: $0, source: source) } }

        for track in tracks {
            let lastCheckpoint = lastRetranscribeCheckpointByMeeting[track.meetingId] ?? 0
            guard let boundary = TranscriptTimelineSplice.nextCheckpointEnd(
                elapsed: elapsed, interval: interval, lastCheckpoint: lastCheckpoint
            ) else { continue }

            retranscribeWindowInFlight = true
            let succeeded = await retranscribeWindow(
                meetingId: track.meetingId,
                source: track.source,
                start: lastCheckpoint,
                end: boundary
            )
            retranscribeWindowInFlight = false

            // Only advance on success so a transient failure leaves the range for
            // a later tick or the on-stop pass to re-cover.
            if succeeded {
                lastRetranscribeCheckpointByMeeting[track.meetingId] = boundary
            }
        }
    }

    /// On-stop tail pass: when mid-recording cadence ran, only the audio since the
    /// last checkpoint remains un-upgraded, so re-transcribe just that tail per
    /// track rather than the whole recording. The window route clamps the end to
    /// the audio actually present, so a slightly generous `total` is safe.
    ///
    /// A post-processing model is frequently still finishing initialization right
    /// as recording stops, so this briefly retries (rather than silently giving
    /// up) before treating the model as genuinely unavailable. If it still isn't
    /// available, the failure is logged unconditionally (not `#if DEBUG`) so it is
    /// visible in a release build, and the meeting is simply left with
    /// `is_post_processed = false` - which the meeting history UI already shows -
    /// so `attemptDeferredTailRetranscription` can finish the job automatically
    /// the next time that meeting is opened with a model available.
    @discardableResult
    func performOnStopTailRetranscription() async -> Bool {
        guard let startTime = recordingStartTime else { return false }

        if postProcessingModel.isEmpty {
            let retryCount = 5
            let retryDelaySeconds: UInt64 = 2
            var modelBecameAvailable = false
            for attempt in 1...retryCount {
                DevLogger.shared.info(
                    "No post-processing model available yet at recording stop; retrying (\(attempt)/\(retryCount))",
                    context: "LiveTranscriptionViewModel"
                )
                try? await Task.sleep(nanoseconds: retryDelaySeconds * 1_000_000_000)
                if !postProcessingModel.isEmpty {
                    modelBecameAvailable = true
                    break
                }
            }
            if !modelBecameAvailable {
                DevLogger.shared.error(
                    "Skipping on-stop transcript improvement: no post-processing model became available after \(retryCount * Int(retryDelaySeconds))s. This meeting will remain marked incomplete until reopened with a model available.",
                    context: "LiveTranscriptionViewModel"
                )
                postProcessingMessage = "Transcript improvement skipped - no local model available"
                return false
            }
        }

        let total = Date().timeIntervalSince(startTime)

        let tracks: [(meetingId: String, source: AudioSource)] = [
            (microphoneMeetingId, AudioSource.microphone),
            (systemAudioMeetingId, AudioSource.systemAudio)
        ].compactMap { id, source in id.map { (meetingId: $0, source: source) } }

        isPostProcessing = true
        postProcessingStartedAutomatically = true
        activePostProcessingMeetingId = selectedMeetingId ?? tracks.first?.meetingId
        postProcessingMessage = "Finishing transcript improvement..."

        var completedAllTracks = !tracks.isEmpty
        for track in tracks {
            let lastCheckpoint = lastRetranscribeCheckpointByMeeting[track.meetingId] ?? 0
            let window = TranscriptTimelineSplice.planOnStopWindow(
                thresholdsEnabled: true, lastCheckpoint: lastCheckpoint, total: total
            )
            let didRetranscribeTail: Bool
            if window.end <= window.start {
                didRetranscribeTail = true
            } else {
                didRetranscribeTail = await retranscribeWindow(
                    meetingId: track.meetingId, source: track.source, start: window.start, end: window.end
                )
            }
            guard didRetranscribeTail else {
                completedAllTracks = false
                continue
            }

            let didPersistCompletion = await markWindowedRetranscriptionComplete(meetingId: track.meetingId)
            if !didPersistCompletion {
                completedAllTracks = false
            }
        }

        isPostProcessing = false
        postProcessingStartedAutomatically = false
        activePostProcessingMeetingId = nil
        postProcessingMessage = completedAllTracks
            ? "Transcript tools complete for all sources"
            : "Transcript improvement did not complete for all sources"
        return completedAllTracks
    }

    /// Re-transcribe a closed window for one track and splice it into the live
    /// transcript. Returns true on success.
    @discardableResult
    func retranscribeWindow(meetingId: String, source: AudioSource, start: Double, end: Double) async -> Bool {
        guard end > start else { return false }

        let port = APIClient.shared.currentPort
        guard let url = URL(string: "http://localhost:\(port)/meetings/\(meetingId)/retranscribe-window") else {
            return false
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "model": postProcessingModel,
            "start_seconds": start,
            "end_seconds": end,
            "live": true
        ]

        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let statusID = UUID()
            updateWindowRetranscriptionStatus(
                id: statusID,
                source: source,
                start: start,
                end: end,
                phase: .running,
                message: "Improving \(source.displayName) transcript..."
            )
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                let code = (response as? HTTPURLResponse)?.statusCode ?? -1
                DevLogger.shared.error("Window re-transcription failed (HTTP \(code)) for \(source.displayName) [\(start), \(end))", context: "LiveTranscriptionViewModel")
                updateWindowRetranscriptionStatus(
                    id: statusID,
                    source: source,
                    start: start,
                    end: end,
                    phase: .failed,
                    message: "Could not improve \(source.displayName) transcript"
                )
                scheduleWindowRetranscriptionStatusClear(id: statusID)
                return false
            }
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let segments = json["segments"] as? [[String: Any]] else {
                updateWindowRetranscriptionStatus(
                    id: statusID,
                    source: source,
                    start: start,
                    end: end,
                    phase: .failed,
                    message: "Could not read improved \(source.displayName) transcript"
                )
                scheduleWindowRetranscriptionStatusClear(id: statusID)
                return false
            }

            updateWindowRetranscriptionStatus(
                id: statusID,
                source: source,
                start: start,
                end: end,
                phase: .applying,
                message: "Updating \(source.displayName) transcript..."
            )
            applyWindowedRetranscription(segments, source: source, start: start, end: end)
            updateWindowRetranscriptionStatus(
                id: statusID,
                source: source,
                start: start,
                end: end,
                phase: .completed,
                message: "Improved \(source.displayName) transcript"
            )
            scheduleWindowRetranscriptionStatusClear(id: statusID)

            #if DEBUG
            DevLogger.shared.info("Spliced \(segments.count) re-transcribed segments for \(source.displayName) [\(start), \(end))", context: "LiveTranscriptionViewModel")
            #endif
            return true
        } catch {
            DevLogger.shared.error("Error re-transcribing window for \(source.displayName) [\(start), \(end)): \(error)", context: "LiveTranscriptionViewModel")
            let statusID = UUID()
            updateWindowRetranscriptionStatus(
                id: statusID,
                source: source,
                start: start,
                end: end,
                phase: .failed,
                message: "Could not improve \(source.displayName) transcript"
            )
            scheduleWindowRetranscriptionStatusClear(id: statusID)
            return false
        }
    }

    private func updateWindowRetranscriptionStatus(
        id: UUID,
        source: AudioSource,
        start: Double,
        end: Double,
        phase: WindowRetranscriptionPhase,
        message: String
    ) {
        windowRetranscriptionStatus = WindowRetranscriptionStatus(
            id: id,
            source: source,
            start: start,
            end: end,
            phase: phase,
            message: message
        )
    }

    private func scheduleWindowRetranscriptionStatusClear(id: UUID) {
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard self?.windowRetranscriptionStatus?.id == id else { return }
            self?.windowRetranscriptionStatus = nil
        }
    }

    func markWindowedRetranscriptionComplete(meetingId: String) async -> Bool {
        let port = APIClient.shared.currentPort
        guard let url = URL(
            string: "http://localhost:\(port)/meetings/\(meetingId)/complete-windowed-retranscription"
        ) else {
            return false
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                let code = (response as? HTTPURLResponse)?.statusCode ?? -1
                DevLogger.shared.error(
                    "Could not mark completed iterative retranscription for \(meetingId) (HTTP \(code))",
                    context: "LiveTranscriptionViewModel"
                )
                return false
            }
            return true
        } catch {
            DevLogger.shared.error(
                "Could not mark completed iterative retranscription for \(meetingId): \(error)",
                context: "LiveTranscriptionViewModel"
            )
            return false
        }
    }

    /// Finish an incomplete transcript upgrade for a *past* meeting that was
    /// left with `is_post_processed = false` because the on-stop tail pass
    /// could not run (no model available at the time recording stopped, or the
    /// app quit before it completed). Called when such a meeting is reopened
    /// and a post-processing model is now available, so the gap left by
    /// `performOnStopTailRetranscription` giving up gets closed automatically
    /// instead of requiring the user to notice and run "Post-Process" by hand.
    ///
    /// Unlike the on-stop pass (which only re-transcribes the tail since the
    /// last mid-recording checkpoint), this covers the full `[0, durationSeconds)`
    /// range since a reopened meeting has no in-memory checkpoint to resume from.
    @discardableResult
    func attemptDeferredTailRetranscription(
        meetingId: String,
        source: AudioSource,
        durationSeconds: Double
    ) async -> Bool {
        guard !postProcessingModel.isEmpty, durationSeconds > 0 else { return false }

        DevLogger.shared.info(
            "Resuming incomplete transcript improvement for \(source.displayName) meeting \(meetingId) on reopen",
            context: "LiveTranscriptionViewModel"
        )

        let didRetranscribe = await retranscribeWindow(
            meetingId: meetingId, source: source, start: 0, end: durationSeconds
        )
        guard didRetranscribe else { return false }

        let didComplete = await markWindowedRetranscriptionComplete(meetingId: meetingId)
        if didComplete {
            DevLogger.shared.info(
                "Completed deferred transcript improvement for \(source.displayName) meeting \(meetingId)",
                context: "LiveTranscriptionViewModel"
            )
        }
        return didComplete
    }
}
