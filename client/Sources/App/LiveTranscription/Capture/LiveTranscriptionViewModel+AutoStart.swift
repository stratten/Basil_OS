import Foundation
import Combine

// MARK: - Armed auto-start (meeting detection)
//
// Drives a fully event-driven start of transcription for a meeting the backend
// mechanical loop detected. Readiness is OBSERVED (models loaded, the detected
// audio process present, its tap created) rather than waited on with timers or
// sleeps, per the project's "react to actual state, never guess durations" rule.
@available(macOS 14.0, *)
extension LiveTranscriptionViewModel {

    /// Arm the view model to begin recording the detected meeting's audio as
    /// soon as the pipeline is ready. Safe to call right after the window opens;
    /// it parks on the published state until each precondition is satisfied.
    func armAutoStart(bundleID: String, pid: Int32?, enableMic: Bool, title: String?, participants: [String]) {
        if let title, !title.isEmpty {
            meetingName = title
        }
        if !participants.isEmpty {
            meetingParticipants = participants.joined(separator: ", ")
        }
        enableMicrophone = enableMic
        systemAudioCaptureMode = .globalOutput
        autoStartedBundleID = bundleID.isEmpty ? nil : bundleID
        statusMessage = "Preparing to record detected meeting…"

        Task { @MainActor in
            await performArmedAutoStart(bundleID: bundleID, pid: pid)
        }
    }

    private func performArmedAutoStart(bundleID: String, pid: Int32?) async {
        // 1. Models loaded (initialize() flips this to .idle once ready).
        await waitUntil($transcriptionState) { $0 != .loadingModels }
        guard !isRecording else { return }

        if systemAudioCaptureMode == .globalOutput {
            startRecording()
            return
        }

        // 2. The detected app appears in the audio-process list (it's producing
        //    audio, so it lands in the "Currently Producing Audio" group). The
        //    process-discovery timer refreshes this until a selection is made.
        if findArmedProcess(bundleID: bundleID, pid: pid, in: availableAudioProcesses) == nil {
            await waitUntil($availableAudioProcesses) { [weak self] groups in
                guard let self else { return true }
                return self.findArmedProcess(bundleID: bundleID, pid: pid, in: groups) != nil
            }
        }
        guard let process = findArmedProcess(bundleID: bundleID, pid: pid, in: availableAudioProcesses),
              !isRecording else { return }

        // 3. Select it, then observe the selection landing before ensuring a tap
        //    exists (the selection observer normally creates it; we guarantee it).
        setSelectedAudioProcess(process)
        if let state = systemAudioState {
            await waitUntil(state.$selectedAudioProcess) { $0?.id == process.id }
        }
        if systemAudioState?.processTap?.process.id != process.id {
            setupSystemAudioTap(for: process)
        }
        guard !isRecording else { return }

        // 4. Tap is in place; start.
        startRecording()
    }

    private func findArmedProcess(bundleID: String, pid: Int32?, in groups: [AudioProcessGroup]) -> AudioProcess? {
        let all = groups.flatMap { $0.processes }
        if let pid, let match = all.first(where: { $0.id == pid }) {
            return match
        }
        if !bundleID.isEmpty, let match = all.first(where: { $0.bundleID == bundleID }) {
            return match
        }
        return nil
    }

    /// Suspend until `predicate` holds for a value emitted by `publisher`.
    /// `@Published` republishes its current value on subscription, so an
    /// already-satisfied condition resolves immediately.
    private func waitUntil<T>(_ publisher: Published<T>.Publisher, _ predicate: @escaping (T) -> Bool) async {
        for await value in publisher.values {
            if Task.isCancelled { return }
            if predicate(value) { return }
        }
    }
}
